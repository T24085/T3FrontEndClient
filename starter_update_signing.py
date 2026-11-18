"""Verify Community Starter release metadata using the Windows CNG trust pin."""
import base64
import ctypes
import hashlib
import struct


PUBLIC_MODULUS = base64.b64decode(
    '1UUB5wRQcXItWGKO0c4zUn4i/xnkv4gyBIhWn9WvE9qUTiLikJ2V9BfrEq+++h1UR86hLb0y6S1lVKRZ/'
    'U34rxUzbpNq0Xiv0uh3EFeH0T/sljtSNp8z1sd/PChMFSr30rZYdcikVV6WM2Mmjp5JQwFbIIe3ENr28H83VY4f1stR+'
    '/WIO5BxmidFjcaUMUCEQ59F+AUstdMs0HNRFCNLeD4pTO1KJDRND4CByOsF3+5UwGK/EPBIxEmts/mC7x3CUk9G1pKLD1'
    'Gt4li8A00sqxZmEcQnPlT3zGXxUMytOaP7KF/v/D4GmBiuOMOHxWhvFiHjleltyuURLpvxgBxi0Xrhy0qjYrCUwPqNBZ'
    '5DKkT0f9KD26GUUWawnbhFrAMSQnLWwJaY1d8q8+pUkg+AjNN0Z+RNm7+f5Hf1ZY2HtJEOAN0TWEZlmMLK3+TRxt+Bx'
    '+wsKH92DUQBDhuo12I8v1VHFlNNwRSyWrX4+5euP8tJ1E2rl5EcvGXzZ5X/R6zJ'
)
PUBLIC_EXPONENT = b'\x01\x00\x01'


class PKCS1PaddingInfo(ctypes.Structure):
    _fields_ = [('algorithm', ctypes.c_wchar_p)]


def verify(payload, signature):
    if len(signature) != len(PUBLIC_MODULUS):
        return False
    cng = ctypes.WinDLL('bcrypt.dll', use_last_error=True, winmode=0x800)
    handle = ctypes.c_void_p
    dword = ctypes.c_uint32
    buffer = ctypes.c_char_p
    cng.BCryptOpenAlgorithmProvider.argtypes = (ctypes.POINTER(handle), ctypes.c_wchar_p, ctypes.c_wchar_p, dword)
    cng.BCryptImportKeyPair.argtypes = (handle, handle, ctypes.c_wchar_p, ctypes.POINTER(handle), buffer, dword, dword)
    cng.BCryptVerifySignature.argtypes = (handle, ctypes.POINTER(PKCS1PaddingInfo), buffer, dword, buffer, dword, dword)
    cng.BCryptDestroyKey.argtypes = (handle,)
    cng.BCryptCloseAlgorithmProvider.argtypes = (handle, dword)
    blob = struct.pack('<6I', 0x31415352, len(PUBLIC_MODULUS) * 8, len(PUBLIC_EXPONENT), len(PUBLIC_MODULUS), 0, 0)
    blob += PUBLIC_EXPONENT + PUBLIC_MODULUS
    provider, key = handle(), handle()
    if cng.BCryptOpenAlgorithmProvider(ctypes.byref(provider), 'RSA', None, 0):
        raise OSError('Windows update signature verification is unavailable.')
    try:
        if cng.BCryptImportKeyPair(provider, None, 'RSAPUBLICBLOB', ctypes.byref(key), blob, len(blob), 0):
            raise OSError('Windows could not load the Community Starter update key.')
        try:
            digest = hashlib.sha256(payload).digest()
            return cng.BCryptVerifySignature(key, ctypes.byref(PKCS1PaddingInfo('SHA256')), digest, len(digest),
                                             signature, len(signature), 2) == 0
        finally:
            cng.BCryptDestroyKey(key)
    finally:
        cng.BCryptCloseAlgorithmProvider(provider, 0)
