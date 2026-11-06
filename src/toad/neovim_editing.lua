-- Application integration, not a Vim interpreter. Neovim interprets every key.
-- One engine serves the whole application; each editing session is one buffer.
local channel = ...
local api = vim.api
local namespace = api.nvim_create_namespace('toad-editor')
vim.opt.swapfile = false
vim.opt.undofile = false
vim.opt.writebackup = false
vim.opt.backup = false
vim.opt.modeline = false
vim.opt.hidden = true
vim.opt.clipboard = ''
vim.opt.shortmess:append('I')

-- Admission is not completion. Only SafeState, which excludes typeahead,
-- mappings and unfinished commands, may certify a completed generation.
-- Each buffer is its own session, so each keeps its own proof.
local generation, completed = {}, {}
local scheduled = false
local function location(position)
  local row = position[2] - 1
  local line = api.nvim_buf_get_lines(0, row, row + 1, true)[1]
  local byte = math.max(0, math.min(position[3] - 1, #line))
  return {row, vim.str_utfindex(line, 'utf-32', byte, false)}
end
local function state()
  local cursor, anchor = vim.fn.getpos('.'), vim.fn.getpos('v')
  local code = vim.fn.mode(1)
  local kind = ({v = 'v', V = 'V', ['\022'] = '\022',
                 s = 'v', S = 'V', ['\019'] = '\022'})[code]
  local regions, selected = {}, ''
  if kind then
    for _, region in ipairs(vim.fn.getregionpos(anchor, cursor, {type = kind, eol = true})) do
      local first, last = location(region[1]), location(region[2])
      last[2] = last[2] + 1
      regions[#regions + 1] = {start = first, ['end'] = last}
    end
    selected = table.concat(vim.fn.getregion(anchor, cursor, {type = kind}), '\n')
    if kind == 'V' then selected = selected .. '\n' end
  end
  return {mode = api.nvim_get_mode(), cursor = location(cursor),
          command_line = vim.fn.getcmdtype() .. vim.fn.getcmdline(),
          regions = regions, selected = selected,
          completed = completed[api.nvim_get_current_buf()] or -1}
end
local function publish()
  vim.rpcnotify(channel, 'toad_editor_state', api.nvim_get_current_buf(), state())
end
local function schedule_publish()
  if scheduled then return end
  scheduled = true
  vim.schedule(function() scheduled = false; publish() end)
end
local function invalidate()
  completed[api.nvim_get_current_buf()] = -1
end
-- A session's buffer publishes its rendering deltas while it is the current
-- buffer; returning to it is an ownership transfer, not another registration.
local subscriptions = {}
local function entered(buffer)
  vim.rpcnotify(channel, 'toad_editor_lines', buffer, {first = 0, last = -1,
    lines = api.nvim_buf_get_lines(buffer, 0, -1, true)})
  if subscriptions[buffer] then return end
  subscriptions[buffer] = true
  api.nvim_buf_attach(buffer, false, {
    on_lines = function(_, buf, tick, first, last, new_last)
      if api.nvim_get_current_buf() == buf then
        completed[buf] = -1
        vim.rpcnotify(channel, 'toad_editor_lines', buf, {first = first, last = last,
                      lines = api.nvim_buf_get_lines(buf, first, new_last, true)})
        schedule_publish()
      end
    end,
    on_detach = function(_, buf) subscriptions[buf] = nil end,
  })
end
api.nvim_create_autocmd('BufEnter', {callback = function(event)
  completed[event.buf] = -1
  entered(event.buf)
  schedule_publish()
end})
api.nvim_create_autocmd({'ModeChanged', 'CursorMoved', 'CursorMovedI',
                        'TextChanged', 'TextChangedI', 'CmdlineChanged'},
                       {callback = schedule_publish})
api.nvim_create_autocmd('SafeState', {callback = function()
  local buf = api.nvim_get_current_buf()
  if generation[buf] and completed[buf] ~= generation[buf] then
    completed[buf] = generation[buf]
    -- Do not queue work from the idle notification: running that work returns
    -- to SafeState and would schedule the next idle notification forever.
    publish()
  end
end})
vim.on_key(function()
  -- lua.txt: on_key runs BEFORE further processing. This invalidates a proof;
  -- it cannot create one, even if the host has already received the input reply.
  invalidate()
  schedule_publish()
end, namespace)

-- Install the editor's actual native arrow declarations, including saved aliases,
-- on its own buffer. Neovim's mapping engine knows the k in fk is an operand, not Up.
local function map(buf, mappings)
  for _, mapping in ipairs(mappings) do
    local lhs, rhs, boundary, modes = unpack(mapping)
    for _, mode in ipairs(modes) do
      vim.keymap.set(mode, lhs, function()
        if vim.v.count == 0 and not vim.fn.mode(1):match('^no') then
          if vim.rpcrequest(channel, 'toad_cursor_boundary', buf, boundary, state()) then
            return ''
          end
        end
        return rhs
      end, {buffer = buf, expr = true, noremap = true, silent = true})
    end
  end
end

-- The mode and cursor a session left its buffer in. Mode is global to the
-- engine, so leaving a buffer cancels any pending operator or command line,
-- and entering it again restores that buffer's own Insert or Replace.
local resumed = {}
-- Normal mode cannot hold a cursor past the line's last character, so an Insert
-- cursor parked at the end of its line resumes with Vim's own append there.
local resume = {i = {inside = 'startinsert', at_end = 'startinsert!'},
                R = {inside = 'startreplace', at_end = 'startinsert!'}}

ToadEditor = {}
function ToadEditor.open(lines, cursor, tabstop, mappings)
  local buf = api.nvim_create_buf(false, true)
  map(buf, mappings)
  vim.bo[buf].buftype = 'nofile'
  vim.bo[buf].bufhidden = 'hide'
  vim.bo[buf].swapfile = false
  vim.bo[buf].tabstop = tabstop
  local undo_levels = vim.bo[buf].undolevels
  vim.bo[buf].undolevels = -1
  api.nvim_buf_set_lines(buf, 0, -1, true, lines)
  vim.bo[buf].undolevels = undo_levels
  local row = cursor[1]
  resumed[buf] = {mode = 'n', cursor = {row + 1,
    vim.str_byteindex(lines[row + 1], 'utf-32', cursor[2], false)}}
  generation[buf], completed[buf] = 0, -1
  return buf
end
function ToadEditor.leave()
  -- Typeahead is ordered, so every key and call this buffer was sent is done by now:
  -- the buffer parks complete, in the mode it will resume, its pending operator cancelled.
  local buf = api.nvim_get_current_buf()
  local code = vim.fn.mode(1):sub(1, 1)
  if not resume[code] then code = 'n' end
  resumed[buf] = {mode = code, cursor = api.nvim_win_get_cursor(0)}
  completed[buf] = generation[buf] or -1
  local parked = state()
  parked.mode = {mode = code, blocking = false}
  parked.regions, parked.selected, parked.command_line = {}, '', ''
  vim.rpcnotify(channel, 'toad_editor_state', buf, parked)
end
function ToadEditor.enter(buf)
  api.nvim_win_set_buf(0, buf)
  local saved = resumed[buf]
  api.nvim_win_set_cursor(0, saved.cursor)
  local command = resume[saved.mode]
  if command then
    local line = api.nvim_buf_get_lines(buf, saved.cursor[1] - 1, saved.cursor[1], true)[1]
    vim.cmd(saved.cursor[2] >= #line and command.at_end or command.inside)
  end
end
function ToadEditor.close(buf)
  resumed[buf], generation[buf], completed[buf] = nil, nil, nil
  api.nvim_buf_delete(buf, {force = true})
end
function ToadEditor.input(buf, serial, keys)
  generation[buf] = math.max(generation[buf], serial)
  completed[buf] = -1
  return api.nvim_input(keys)
end
function ToadEditor.call(buf, serial, operation, arguments)
  generation[buf] = math.max(generation[buf], serial)
  completed[buf] = -1
  local result = operation(unpack(arguments))
  schedule_publish()
  return result
end
function ToadEditor.load(text)
  api.nvim_buf_set_lines(0, 0, -1, true, vim.split(text, '\n', {plain = true}))
  api.nvim_win_set_cursor(0, {1, 0})
end
function ToadEditor.cursor_end()
  local count = api.nvim_buf_line_count(0)
  local line = api.nvim_buf_get_lines(0, count - 1, count, true)[1]
  api.nvim_win_set_cursor(0, {count, #line})
end
local function byte_position(location)
  -- Convert application codepoint coordinates against the actual buffer now,
  -- not against a potentially older Python rendering when the edit was queued.
  local row = math.max(0, math.min(location[1], api.nvim_buf_line_count(0) - 1))
  local line = api.nvim_buf_get_lines(0, row, row + 1, true)[1]
  local column = math.max(0, math.min(location[2], vim.str_utfindex(line, 'utf-32')))
  return {row + 1, vim.str_byteindex(line, 'utf-32', column, false)}
end
function ToadEditor.cursor(location)
  api.nvim_win_set_cursor(0, byte_position(location))
end
function ToadEditor.select(first, last)
  -- TextArea API ranges are end-exclusive; Neovim owns the actual Visual state.
  first, last = byte_position(first), byte_position(last)
  local row, byte = last[1], last[2]
  if byte == 0 and row > 1 then
    row = row - 1
    byte = #api.nvim_buf_get_lines(0, row - 1, row, true)[1]
  end
  local line = api.nvim_buf_get_lines(0, row - 1, row, true)[1]
  local characters = vim.str_utfindex(line, 'utf-32', byte, false)
  byte = vim.str_byteindex(line, 'utf-32', math.max(0, characters - 1), false)
  api.nvim_win_set_cursor(0, first)
  vim.cmd.normal({args = {'v'}, bang = true})
  api.nvim_win_set_cursor(0, {row, byte})
end
function ToadEditor.insert(lines, position, maintain_offset)
  -- MessagePack nil in an argument array enters Lua as vim.NIL.
  if position == vim.NIL then
    local cursor = api.nvim_win_get_cursor(0)
    local line = api.nvim_get_current_line()
    position = {cursor[1] - 1, vim.str_utfindex(line, 'utf-32', cursor[2], false)}
  end
  return ToadEditor.replace(position, position, lines, maintain_offset)
end
function ToadEditor.replace(first, last, lines, maintain_offset)
  local top, bottom = byte_position(first), byte_position(last)
  local top_row, top_byte = top[1] - 1, top[2]
  local bottom_row, bottom_byte = bottom[1] - 1, bottom[2]
  local cursor = api.nvim_win_get_cursor(0)
  local mark = api.nvim_buf_set_extmark(0, namespace, cursor[1] - 1, cursor[2],
                                      {right_gravity = true})
  api.nvim_buf_set_text(0, top_row, top_byte, bottom_row, bottom_byte, lines)
  local retained = api.nvim_buf_get_extmark_by_id(0, namespace, mark, {})
  api.nvim_buf_del_extmark(0, namespace, mark)
  if maintain_offset then
    api.nvim_win_set_cursor(0, {retained[1] + 1, retained[2]})
  else
    local row = top_row + #lines - 1
    local column = #lines[#lines] + (#lines == 1 and top_byte or 0)
    api.nvim_win_set_cursor(0, {row + 1, column})
  end
end
