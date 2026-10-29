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
vim.opt.virtualedit = 'onemore'
vim.opt.shortmess:append('I')
vim.bo.buftype = 'nofile'
vim.bo.bufhidden = 'hide'

local function state()
  local cursor = vim.fn.getpos('.')
  local anchor = vim.fn.getpos('v')
  return {{cursor[2], cursor[3]}, {anchor[2], anchor[3]},
          vim.fn.mode(1), vim.fn.state(), vim.v.count, vim.fn.getcmdline()}
end
local function publish()
  vim.rpcnotify(1, 'toad_editor_state', unpack(state()))
end
api.nvim_create_autocmd({'ModeChanged', 'CursorMoved', 'CursorMovedI',
                        'TextChanged', 'TextChangedI', 'CmdlineChanged', 'SafeState'},
                       {callback = publish})
vim.on_key(function() vim.schedule(publish) end, namespace)

-- Install the actual native arrow declarations, including saved aliases, inside
-- Neovim. Its mapping engine knows that the k in fk is an operand, not Up.
for _, mapping in ipairs(mappings) do
  local lhs, rhs, native = unpack(mapping)
  for _, mode in ipairs({'', 'i'}) do
    vim.keymap.set(mode, lhs, function()
      if vim.v.count == 0 and not vim.fn.mode(1):match('^no') then
        if vim.rpcrequest(1, 'toad_cursor_boundary', native) then return '' end
      end
      return api.nvim_replace_termcodes(rhs, true, false, true)
    end, {expr = true, noremap = true, silent = true})
  end
end

ToadEditor = {}
function ToadEditor.load(text)
  api.nvim_buf_set_lines(0, 0, -1, true, vim.split(text, '\n', {plain = true}))
  local lines = api.nvim_buf_get_lines(0, 0, -1, true)
  api.nvim_win_set_cursor(0, {#lines, #lines[#lines]})
end
function ToadEditor.replace(top, top_byte, bottom, bottom_byte, lines, maintain_offset)
  local cursor = api.nvim_win_get_cursor(0)
  local mark = api.nvim_buf_set_extmark(0, namespace, cursor[1] - 1, cursor[2],
                                      {right_gravity = true})
  api.nvim_buf_set_text(0, top, top_byte, bottom, bottom_byte, lines)
  local retained = api.nvim_buf_get_extmark_by_id(0, namespace, mark, {})
  api.nvim_buf_del_extmark(0, namespace, mark)
  if maintain_offset then
    api.nvim_win_set_cursor(0, {retained[1] + 1, retained[2]})
  else
    local row = top + #lines - 1
    local column = #lines[#lines] + (#lines == 1 and top_byte or 0)
    api.nvim_win_set_cursor(0, {row + 1, column})
  end
end
