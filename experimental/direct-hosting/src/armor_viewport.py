"""Interactive Windows armor viewport for local, prepared model assets."""
import ctypes as C
from ctypes import wintypes as W
import math
import struct


class PixelFormat(C.Structure):
    _fields_ = [
        ('size', W.WORD), ('version', W.WORD), ('flags', W.DWORD),
        ('pixel_type', C.c_ubyte), ('color_bits', C.c_ubyte),
        ('channels', C.c_ubyte * 13), ('depth_bits', C.c_ubyte),
        ('stencil_bits', C.c_ubyte), ('aux_buffers', C.c_ubyte),
        ('layer_type', C.c_ubyte), ('reserved', C.c_ubyte),
        ('layer_mask', W.DWORD), ('visible_mask', W.DWORD), ('damage_mask', W.DWORD),
    ]


HEADER = struct.Struct('<4sI')
VERTEX = struct.Struct('<10f')
MAX_VERTICES = 360_000


def read_model(path):
    with path.open('rb') as stream:
        return decode_model(stream.read(HEADER.size + MAX_VERTICES * VERTEX.size + 1))


def decode_model(data):
    if len(data) < HEADER.size:
        raise ValueError('Incomplete armor model.')
    marker, count = HEADER.unpack_from(data)
    if marker != b'T3M1' or not 3 <= count <= MAX_VERTICES or count % 3:
        raise ValueError('Unsupported armor model.')
    expected = count * VERTEX.size
    if len(data) != HEADER.size + expected:
        raise ValueError('Invalid armor model size.')
    return count, C.create_string_buffer(data[HEADER.size:], expected)


class ArmorViewport:
    def __init__(self, frame):
        self.frame = frame
        self.context = None
        self.dc = None
        self.model = None
        self.drag_start = None
        self.pending = None
        self.reset_camera()
        self.user = C.windll.user32
        self.gdi = C.windll.gdi32
        self.gl = C.WinDLL('opengl32.dll', use_last_error=True)
        self._bind_functions()
        frame.bind('<Map>', self.redraw)
        frame.bind('<Configure>', self.redraw)
        frame.bind('<Expose>', self.redraw)
        frame.bind('<Destroy>', self.close)
        frame.bind('<ButtonPress-1>', self.start_drag)
        frame.bind('<B1-Motion>', self.drag)
        frame.bind('<ButtonRelease-1>', self.end_drag)
        frame.bind('<MouseWheel>', self.wheel)
        frame.bind('<Left>', lambda _: self.orbit(-12, 0))
        frame.bind('<Right>', lambda _: self.orbit(12, 0))
        frame.bind('<Up>', lambda _: self.orbit(0, -10))
        frame.bind('<Down>', lambda _: self.orbit(0, 10))
        frame.bind('<KeyPress-plus>', lambda _: self.zoom(0.88))
        frame.bind('<KeyPress-minus>', lambda _: self.zoom(1.14))
        frame.bind('<Home>', lambda _: self.reset_camera())

    def _bind_functions(self):
        pointer = C.c_void_p
        integer, unsigned = C.c_int, C.c_uint
        single, double = C.c_float, C.c_double
        groups = (
            (self.user, {'GetDC': (W.HDC, W.HWND), 'ReleaseDC': (integer, W.HWND, W.HDC)}),
            (self.gdi, {
                'ChoosePixelFormat': (integer, W.HDC, C.POINTER(PixelFormat)),
                'SetPixelFormat': (W.BOOL, W.HDC, integer, C.POINTER(PixelFormat)),
                'SwapBuffers': (W.BOOL, W.HDC),
            }),
            (self.gl, {
                'wglCreateContext': (pointer, W.HDC), 'wglDeleteContext': (W.BOOL, pointer),
                'wglMakeCurrent': (W.BOOL, W.HDC, pointer),
                'glViewport': (None, integer, integer, integer, integer),
                'glClearColor': (None, single, single, single, single), 'glClear': (None, unsigned),
                'glMatrixMode': (None, unsigned), 'glLoadIdentity': (None,),
                'glFrustum': (None, double, double, double, double, double, double),
                'glTranslatef': (None, single, single, single),
                'glRotatef': (None, single, single, single, single),
                'glEnable': (None, unsigned),
                'glColorMaterial': (None, unsigned, unsigned),
                'glLightfv': (None, unsigned, unsigned, C.POINTER(single)),
                'glInterleavedArrays': (None, unsigned, integer, pointer),
                'glDrawArrays': (None, unsigned, integer, integer),
            }),
        )
        for library, functions in groups:
            for name, (result, *arguments) in functions.items():
                function = getattr(library, name)
                function.restype = result
                function.argtypes = arguments

    def initialize(self):
        self.window = self.frame.winfo_id()
        self.dc = self.user.GetDC(self.window)
        fmt = PixelFormat(size=C.sizeof(PixelFormat), version=1, flags=0x25, color_bits=24, depth_bits=24)
        chosen = self.gdi.ChoosePixelFormat(self.dc, C.byref(fmt)) if self.dc else 0
        if not chosen or not self.gdi.SetPixelFormat(self.dc, chosen, C.byref(fmt)):
            self.close()
            raise OSError('The armor viewport could not select a pixel format.')
        self.context = self.gl.wglCreateContext(self.dc)
        if not self.context or not self.gl.wglMakeCurrent(self.dc, self.context):
            self.close()
            raise OSError('The armor viewport could not open an OpenGL context.')
        self.gl.wglMakeCurrent(None, None)

    def show(self, model):
        if self.context is None:
            self.initialize()
        self.model = model
        self.redraw()

    def reset_camera(self):
        self.yaw, self.pitch, self.distance = -24.0, 7.0, 3.6
        self.redraw()

    def orbit(self, dx, dy):
        self.yaw = (self.yaw + dx) % 360
        self.pitch = max(-75, min(75, self.pitch + dy))
        self.redraw()

    def zoom(self, factor):
        self.distance = max(1.65, min(8.0, self.distance * factor))
        self.redraw()

    def start_drag(self, event):
        self.frame.focus_set()
        self.drag_start = event.x, event.y

    def drag(self, event):
        if self.drag_start is not None:
            x, y = self.drag_start
            self.drag_start = event.x, event.y
            self.orbit((event.x-x)*0.65, (event.y-y)*0.55)

    def end_drag(self, _event):
        self.drag_start = None

    def wheel(self, event):
        if event.delta:
            self.zoom(0.88 if event.delta > 0 else 1.14)

    def redraw(self, _event=None):
        if self.model is not None and self.pending is None:
            self.pending = self.frame.after_idle(self.draw)

    def draw(self):
        self.pending = None
        if self.model is None or not self.frame.winfo_ismapped():
            return
        if not self.gl.wglMakeCurrent(self.dc, self.context):
            return
        try:
            gl = self.gl
            width, height = self.frame.winfo_width(), self.frame.winfo_height()
            near = 0.2
            half_height = near * math.tan(math.radians(21))
            half_width = half_height * width / max(height, 1)
            gl.glViewport(0, 0, width, height)
            gl.glClearColor(0.075, 0.125, 0.18, 1)
            gl.glClear(0x4100)
            gl.glMatrixMode(0x1701)
            gl.glLoadIdentity()
            gl.glFrustum(-half_width, half_width, -half_height, half_height, near, 24)
            gl.glMatrixMode(0x1700)
            gl.glLoadIdentity()
            gl.glEnable(0x0B71)
            gl.glEnable(0x0B50)
            gl.glEnable(0x4000)
            gl.glEnable(0x0B57)
            gl.glColorMaterial(0x0408, 0x1602)
            gl.glLightfv(0x4000, 0x1203, (C.c_float * 4)(0.5, 0.8, 1, 0))
            gl.glLightfv(0x4000, 0x1200, (C.c_float * 4)(0.36, 0.36, 0.4, 1))
            gl.glTranslatef(0, 0, -self.distance)
            gl.glRotatef(self.pitch, 1, 0, 0)
            gl.glRotatef(self.yaw, 0, 1, 0)
            count, data = self.model
            gl.glInterleavedArrays(0x2A26, 0, C.cast(data, C.c_void_p))
            gl.glDrawArrays(4, 0, count)
            self.gdi.SwapBuffers(self.dc)
        finally:
            self.gl.wglMakeCurrent(None, None)

    def close(self, _event=None):
        if self.pending is not None:
            self.frame.after_cancel(self.pending)
            self.pending = None
        if self.context is not None:
            self.gl.wglDeleteContext(self.context)
            self.context = None
        if self.dc is not None:
            self.user.ReleaseDC(self.window, self.dc)
            self.dc = None
