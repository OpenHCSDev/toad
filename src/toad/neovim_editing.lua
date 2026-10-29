-- Application integration, not a Vim interpreter. Neovim interprets every key.
local mappings = ...
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
vim.bo.buftype = 'nofile'
vim.bo.bufhidden = 'hide'

local function state()
  local cursor, anchor = vim.fn.getpos('.'), vim.fn.getpos('v')
  local code = vim.fn.mode(1)
  local kind = ({v = 'v', V = 'V', ['\022'] = '\022',
                 s = 'v', S = 'V', ['\019'] = '\022'})[code]
  local regions, selected = {}, ''
  if kind then
    regions = vim.fn.getregionpos(anchor, cursor, {type = kind, eol = true})
    selected = table.concat(vim.fn.getregion(anchor, cursor, {type = kind}), '\n')
    if kind == 'V' then selected = selected .. '\n' end
  end
  -- Mode/blocking are read by the host through the fast nvim_get_mode API.
  -- Running a Lua callback is not evidence that a pending operand has finished.
  return {{cursor[2], cursor[3]},
          vim.fn.getcmdtype() .. vim.fn.getcmdline(), regions, selected}
end
local function publish()
  vim.rpcnotify(1, 'toad_editor_state', unpack(state()))
end
-- Buffer subscriptions belong to this engine, including :edit/:buffer changes.
-- Only its current buffer publishes rendering deltas; returning to a buffer is
-- an ownership transfer, not another callback registration.
local subscriptions = {}
local function entered(buffer)
  vim.rpcnotify(1, 'nvim_buf_lines_event', buffer,
    api.nvim_buf_get_changedtick(buffer), 0, -1,
    api.nvim_buf_get_lines(buffer, 0, -1, true), false)
  if subscriptions[buffer] then return end
  subscriptions[buffer] = true
  api.nvim_buf_attach(buffer, false, {
    on_lines = function(_, buf, tick, first, last, new_last)
      if api.nvim_get_current_buf() == buf then
        vim.rpcnotify(1, 'nvim_buf_lines_event', buf, tick, first, last,
                      api.nvim_buf_get_lines(buf, first, new_last, true), false)
      end
    end,
    on_detach = function(_, buf) subscriptions[buf] = nil end,
  })
end
api.nvim_create_autocmd('BufEnter', {callback = function(event) entered(event.buf); publish() end})
entered(api.nvim_get_current_buf())
api.nvim_create_autocmd({'ModeChanged', 'CursorMoved', 'CursorMovedI',
                        'TextChanged', 'TextChangedI', 'CmdlineChanged', 'SafeState'},
                       {callback = publish})
vim.on_key(function() vim.schedule(publish) end, namespace)

-- Install the actual native arrow declarations, including saved aliases, inside
-- Neovim. Its mapping engine knows that the k in fk is an operand, not Up.
for _, mapping in ipairs(mappings) do
  local lhs, rhs, boundary = unpack(mapping)
  for _, mode in ipairs({'', 'i'}) do
    vim.keymap.set(mode, lhs, function()
      if vim.v.count == 0 and not vim.fn.mode(1):match('^no') then
        if vim.rpcrequest(1, 'toad_cursor_boundary', boundary) then return '' end
      end
      return api.nvim_replace_termcodes(rhs, true, false, true)
    end, {expr = true, noremap = true, silent = true})
  end
end

ToadEditor = {state = state}
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
