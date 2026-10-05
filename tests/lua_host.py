"""Execute the real bridge in Lua 5.4, with an explicit mock BizHawk host.

This tests Lua parsing, actual filesystem IPC, controller writes, and yield
logic. It cannot validate BizHawk's rendering, main loop, or emulator core.
"""

import ctypes
import ctypes.util
import json
from pathlib import Path
import threading


LUA_LIBRARY = ctypes.util.find_library("lua5.4")


class LuaHost:
    def __init__(self, root):
        self.root = root
        lib = ctypes.CDLL(LUA_LIBRARY)
        self.lib = lib
        lib.luaL_newstate.restype = ctypes.c_void_p
        lib.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lib.luaL_loadbufferx.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t,
                                      ctypes.c_char_p, ctypes.c_char_p]
        lib.luaL_loadbufferx.restype = ctypes.c_int
        lib.lua_pcallk.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_ssize_t, ctypes.c_void_p]
        lib.lua_pcallk.restype = ctypes.c_int
        lib.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.lua_tolstring.restype = ctypes.c_char_p
        lib.lua_close.argtypes = [ctypes.c_void_p]
        self.state = lib.luaL_newstate()
        lib.luaL_openlibs(self.state)
        self.error = None
        self.stop = threading.Event()
        source = Path(__file__).resolve().parents[1] / "gpt64" / "bridge.lua"
        prelude = r'''
local root = ROOT
local frames, paused = 100, true
local current_buttons, current_axes = {}, {}
local names = {"A", "B", "Z", "Start", "L", "R", "C Up", "C Down", "C Left", "C Right", "A Up"}
client = {
    pause = function() paused = true end,
    unpause = function() paused = false end,
    ispaused = function() return paused end,
    clearautohold = function() end,
    setscreenshotosd = function(value) assert(value == false) end,
    frameskip = function(value) assert(value == 0) end,
    screenshot = function(path)
        assert(paused)
        local f = assert(io.open(path, "wb"))
        f:write("\137PNG\r\n\26\n", tostring(frames))
        f:close()
    end
}
joypad = {
    get = function(player)
        assert(player == 1)
        local result = {["X Axis"] = 0, ["Y Axis"] = 0}
        for _, name in ipairs(names) do result[name] = false end
        return result
    end,
    set = function(value, player)
        assert(player == 1)
        current_buttons = value
    end,
    setanalog = function(value, player)
        assert(player == 1)
        current_axes = value
    end
}
emu = {
    getsystemid = function() return "N64" end,
    framecount = function() return frames end,
    frameadvance = function()
        assert(not paused, "frameadvance requires an unpaused emulator")
        frames = frames + 1
        local f = assert(io.open(root .. "/inputs.log", "a"))
        f:write(string.format("%d %d %d %s %s\n", frames, current_axes["X Axis"],
                             current_axes["Y Axis"], tostring(current_buttons.A), tostring(current_buttons.Z)))
        f:close()
        coroutine.yield()
    end,
    yield = function()
        assert(paused, "idle must be paused")
        assert(current_axes["X Axis"] == 0 and current_axes["Y Axis"] == 0, "idle axes must be neutral")
        for _, v in pairs(current_buttons) do assert(v == false, "idle buttons must be neutral") end
        coroutine.yield()
    end
}
console = {log = function(message)
    local f = assert(io.open(root .. "/console.log", "a")); f:write(message, "\n"); f:close()
end}
event = {onexit = function(callback) exit_callback = callback end}
local co = coroutine.create(function() assert(loadfile(SOURCE))({root = root}) end)
function tick()
    if coroutine.status(co) ~= "dead" then
        local ok, err = coroutine.resume(co)
        assert(ok, err)
    end
end
'''.replace("ROOT", json.dumps(root.as_posix())).replace("SOURCE", json.dumps(source.as_posix()))
        self.execute(prelude)
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def execute(self, text):
        code = text.encode()
        result = self.lib.luaL_loadbufferx(self.state, code, len(code), b"test_host", None)
        if result == 0:
            result = self.lib.lua_pcallk(self.state, 0, 0, 0, 0, None)
        if result:
            raise RuntimeError(self.lib.lua_tolstring(self.state, -1, None).decode())

    def loop(self):
        try:
            while not self.stop.wait(0.001):
                self.execute("tick()")
        except BaseException as e:
            self.error = e

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        assert not self.thread.is_alive()
        self.lib.lua_close(self.state)
        if self.error:
            raise self.error
