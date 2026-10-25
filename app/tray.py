"""Run the local server and its Windows notification-area icon in one process."""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
import sys
import threading
import time
import urllib.request
import webbrowser
from ctypes import wintypes

import uvicorn

from app.core.config import CONFIG, STATE
from app.main import app
from app.services import updater
from app.version import VERSION

LOGGER = logging.getLogger(__name__)

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_USER = 0x0400
WM_CONTEXTMENU = 0x007B
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIM_MODIFY = 0x00000001
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
ERROR_ALREADY_EXISTS = 183
NOTIFICATION_MESSAGE = WM_USER + 1
TIMER_ID = 1
RESTART_DELAY_SECONDS = 5
MAX_RESTART_DELAY_SECONDS = 300

MENU_OPEN = 1001
MENU_RESTART = 1002
MENU_STOP = 1003
MENU_EXIT = 1004
MENU_CHECK_UPDATES = 1005
UPDATE_SHUTDOWN_MESSAGE = WM_USER + 2
UPDATE_CHECK_INTERVAL_SECONDS = 6 * 60 * 60
UPDATE_STARTUP_DELAY_SECONDS = 60
MB_YESNO = 0x00000004
MB_ICONINFORMATION = 0x00000040
MB_TOPMOST = 0x00040000
IDYES = 6

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class Guid(ctypes.Structure):
    _fields_ = [
        ('data1', wintypes.DWORD),
        ('data2', wintypes.WORD),
        ('data3', wintypes.WORD),
        ('data4', ctypes.c_ubyte * 8),
    ]


class NotifyIconData(ctypes.Structure):
    _fields_ = [
        ('size', wintypes.DWORD),
        ('window', wintypes.HWND),
        ('identifier', wintypes.UINT),
        ('flags', wintypes.UINT),
        ('callback_message', wintypes.UINT),
        ('icon', wintypes.HICON),
        ('tooltip', wintypes.WCHAR * 128),
        ('state', wintypes.DWORD),
        ('state_mask', wintypes.DWORD),
        ('information', wintypes.WCHAR * 256),
        ('timeout_or_version', wintypes.UINT),
        ('information_title', wintypes.WCHAR * 64),
        ('information_flags', wintypes.DWORD),
        ('item_guid', Guid),
        ('balloon_icon', wintypes.HICON),
    ]


class WindowClass(ctypes.Structure):
    _fields_ = [
        ('style', wintypes.UINT),
        ('window_procedure', WNDPROC),
        ('class_extra', ctypes.c_int),
        ('window_extra', ctypes.c_int),
        ('instance', wintypes.HINSTANCE),
        ('icon', wintypes.HICON),
        ('cursor', wintypes.HANDLE),
        ('background', wintypes.HBRUSH),
        ('menu_name', wintypes.LPCWSTR),
        ('class_name', wintypes.LPCWSTR),
    ]


class Point(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]


def configure_logging() -> None:
    """Write server and tray diagnostics to a local file without a console."""
    STATE.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=STATE / 'tray.log',
        encoding='utf-8',
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        force=True,
    )


class DocsLocalTray:
    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL('user32', use_last_error=True)
        self._shell32 = ctypes.WinDLL('shell32', use_last_error=True)
        self._kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self._configure_windows_api()

        ctypes.set_last_error(0)
        self._mutex = self._kernel32.CreateMutexW(
            None,
            True,
            'Local\\DocsLocalTray',
        )
        mutex_error = ctypes.get_last_error()
        if not self._mutex:
            raise ctypes.WinError(mutex_error)
        if mutex_error == ERROR_ALREADY_EXISTS:
            self._kernel32.CloseHandle(self._mutex)
            raise RuntimeError('O ícone do Docs Local já está em execução.')

        self._server: uvicorn.Server | None = None
        self._server_thread: threading.Thread | None = None
        self._server_stopped_by_user = False
        self._next_restart_at = 0.0
        self._restart_delay = RESTART_DELAY_SECONDS
        self._window_handle: int | None = None
        self._icon_handle: int | None = None
        self._owns_icon = False
        self._next_update_check_at = time.monotonic() + UPDATE_STARTUP_DELAY_SECONDS
        self._update_lock = threading.Lock()
        self._notify_data = NotifyIconData()
        self._window_procedure = WNDPROC(self._handle_window_message)
        self._class_name = f'DocsLocalTrayWindow_{os.getpid()}'

    def _configure_windows_api(self) -> None:
        self._kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        self._user32.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
        self._user32.RegisterClassW.restype = wintypes.ATOM
        self._user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            ctypes.c_void_p,
            wintypes.HINSTANCE,
            ctypes.c_void_p,
        ]
        self._user32.CreateWindowExW.restype = wintypes.HWND
        self._user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self._user32.LoadImageW.restype = wintypes.HANDLE
        self._user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        self._user32.LoadIconW.restype = wintypes.HICON
        self._user32.DestroyIcon.argtypes = [wintypes.HICON]
        self._user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.DefWindowProcW.restype = LRESULT
        self._user32.SetTimer.argtypes = [
            wintypes.HWND,
            ctypes.c_size_t,
            wintypes.UINT,
            ctypes.c_void_p,
        ]
        self._user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(Point)]
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.CreatePopupMenu.restype = wintypes.HMENU
        self._user32.AppendMenuW.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_size_t,
            wintypes.LPCWSTR,
        ]
        self._user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            ctypes.c_void_p,
        ]
        self._user32.DestroyMenu.argtypes = [wintypes.HMENU]
        self._user32.DestroyWindow.argtypes = [wintypes.HWND]
        self._user32.PostQuitMessage.argtypes = [ctypes.c_int]
        self._user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
        self._user32.MessageBoxW.restype = ctypes.c_int
        self._user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self._user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self._user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.GetMessageW.restype = ctypes.c_int
        self._user32.CreatePopupMenu.restype = wintypes.HMENU
        self._user32.TrackPopupMenu.restype = wintypes.UINT
        self._shell32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(NotifyIconData),
        ]
        self._shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    @property
    def server_url(self) -> str:
        host = CONFIG['server']['host']
        port = int(CONFIG['server']['port'])
        return f'http://{host}:{port}'

    def run(self) -> None:
        try:
            self._start_server()
            self._create_hidden_window()
            self._add_notification_icon()
            self._user32.SetTimer(self._window_handle, TIMER_ID, 5000, None)
            self._run_message_loop()
        finally:
            self._remove_notification_icon()
            self._stop_server()
            if self._window_handle:
                self._user32.DestroyWindow(self._window_handle)
            self._kernel32.ReleaseMutex(self._mutex)
            self._kernel32.CloseHandle(self._mutex)

    def _create_hidden_window(self) -> None:
        instance = self._kernel32.GetModuleHandleW(None)
        window_class = WindowClass(
            style=0,
            window_procedure=self._window_procedure,
            class_extra=0,
            window_extra=0,
            instance=instance,
            icon=None,
            cursor=None,
            background=None,
            menu_name=None,
            class_name=self._class_name,
        )
        if not self._user32.RegisterClassW(ctypes.byref(window_class)):
            raise ctypes.WinError(ctypes.get_last_error())

        self._window_handle = self._user32.CreateWindowExW(
            0,
            self._class_name,
            self._class_name,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            instance,
            None,
        )
        if not self._window_handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def _add_notification_icon(self) -> None:
        icon_path = Path(__file__).parent / 'static' / 'docs-local.ico'
        if icon_path.is_file():
            self._icon_handle = self._user32.LoadImageW(
                None,
                str(icon_path),
                IMAGE_ICON,
                32,
                32,
                LR_LOADFROMFILE,
            )
            self._owns_icon = bool(self._icon_handle)

        if not self._icon_handle:
            self._icon_handle = self._user32.LoadIconW(
                None,
                ctypes.c_void_p(32512),
            )
            LOGGER.warning('Ícone próprio indisponível; usando o ícone padrão do Windows.')
        else:
            LOGGER.info('Ícone próprio do Docs Local carregado.')

        server_is_active = bool(self._server and self._server.started)
        tooltip = (
            'Docs Local — servidor ativo'
            if server_is_active
            else 'Docs Local — servidor parado'
        )
        self._notify_data = NotifyIconData(
            size=ctypes.sizeof(NotifyIconData),
            window=self._window_handle,
            identifier=1,
            flags=NIF_MESSAGE | NIF_ICON | NIF_TIP,
            callback_message=NOTIFICATION_MESSAGE,
            icon=self._icon_handle,
            tooltip=tooltip,
        )
        if not self._shell32.Shell_NotifyIconW(
            NIM_ADD,
            ctypes.byref(self._notify_data),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def _remove_notification_icon(self) -> None:
        if self._notify_data.window:
            self._shell32.Shell_NotifyIconW(
                NIM_DELETE,
                ctypes.byref(self._notify_data),
            )
        if self._owns_icon and self._icon_handle:
            self._user32.DestroyIcon(self._icon_handle)
            self._icon_handle = None

    def _set_tooltip(self, message: str) -> None:
        self._notify_data.tooltip = message[:127]
        self._shell32.Shell_NotifyIconW(
            NIM_MODIFY,
            ctypes.byref(self._notify_data),
        )

    def _run_message_loop(self) -> None:
        message = wintypes.MSG()
        while True:
            result = self._user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result <= 0:
                break
            self._user32.TranslateMessage(ctypes.byref(message))
            self._user32.DispatchMessageW(ctypes.byref(message))

    def _handle_window_message(
        self,
        window: int,
        message: int,
        word: int,
        long: int,
    ) -> int:
        if message == NOTIFICATION_MESSAGE:
            if long in (WM_CONTEXTMENU, WM_RBUTTONUP):
                self._show_context_menu()
            elif long == WM_LBUTTONDBLCLK:
                self._open_docs()
            return 0

        if message == WM_TIMER and word == TIMER_ID:
            self._check_server()
            self._check_update_schedule()
            return 0

        if message == UPDATE_SHUTDOWN_MESSAGE:
            self._server_stopped_by_user = True
            self._user32.DestroyWindow(self._window_handle)
            return 0

        if message == WM_DESTROY:
            self._user32.KillTimer(window, TIMER_ID)
            self._user32.PostQuitMessage(0)
            return 0

        return self._user32.DefWindowProcW(window, message, word, long)

    def _show_context_menu(self) -> None:
        menu = self._user32.CreatePopupMenu()
        if not menu:
            LOGGER.error('Não foi possível criar o menu da bandeja.')
            return

        self._user32.AppendMenuW(menu, MF_STRING, MENU_OPEN, 'Abrir Docs Local')
        self._user32.AppendMenuW(menu, MF_STRING, MENU_RESTART, 'Reiniciar servidor')
        self._user32.AppendMenuW(menu, MF_STRING, MENU_STOP, 'Encerrar servidor')
        self._user32.AppendMenuW(menu, MF_STRING, MENU_CHECK_UPDATES, 'Verificar atualizações')
        self._user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        self._user32.AppendMenuW(menu, MF_STRING, MENU_EXIT, 'Sair do Docs Local')

        point = Point()
        self._user32.GetCursorPos(ctypes.byref(point))
        self._user32.SetForegroundWindow(self._window_handle)
        command = self._user32.TrackPopupMenu(
            menu,
            TPM_RIGHTBUTTON | TPM_RETURNCMD,
            point.x,
            point.y,
            0,
            self._window_handle,
            None,
        )
        self._user32.DestroyMenu(menu)
        self._dispatch_menu_command(command)

    def _dispatch_menu_command(self, command: int) -> None:
        if command == MENU_OPEN:
            self._server_stopped_by_user = False
            if self._start_server():
                webbrowser.open(self.server_url)
        elif command == MENU_RESTART:
            self._server_stopped_by_user = False
            self._stop_server()
            time.sleep(0.5)
            self._start_server()
        elif command == MENU_STOP:
            self._server_stopped_by_user = True
            self._stop_server()
        elif command == MENU_EXIT:
            self._server_stopped_by_user = True
            self._stop_server()
            self._user32.DestroyWindow(self._window_handle)
        elif command == MENU_CHECK_UPDATES:
            self._start_update_check(manual=True)

    def _open_docs(self) -> None:
        self._server_stopped_by_user = False
        if self._start_server():
            webbrowser.open(self.server_url)

    def _start_server(self) -> bool:
        if self._server_thread and self._server_thread.is_alive():
            return True

        LOGGER.info('Iniciando o servidor local.')
        configuration = uvicorn.Config(
            app,
            host=CONFIG['server']['host'],
            port=int(CONFIG['server']['port']),
            workers=1,
            access_log=False,
            log_config=None,
        )
        self._server = uvicorn.Server(configuration)
        self._server_thread = threading.Thread(
            target=self._run_server,
            name='docs-local-server',
            daemon=True,
        )
        self._server_thread.start()

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self._server.started:
                LOGGER.info('Servidor disponível em %s.', self.server_url)
                self._restart_delay = RESTART_DELAY_SECONDS
                self._set_tooltip('Docs Local — servidor ativo')
                return True
            if not self._server_thread.is_alive():
                break
            time.sleep(0.1)

        LOGGER.error('O servidor não iniciou dentro do tempo esperado.')
        self._set_tooltip('Docs Local — servidor parado')
        self._next_restart_at = time.monotonic() + self._restart_delay
        self._restart_delay = min(
            self._restart_delay * 2,
            MAX_RESTART_DELAY_SECONDS,
        )
        return False

    def _run_server(self) -> None:
        try:
            if self._server is not None:
                self._server.run()
        except BaseException:
            LOGGER.exception('O servidor local encerrou com erro.')

    def _stop_server(self) -> None:
        if self._server is None or self._server_thread is None:
            return

        LOGGER.info('Encerrando o servidor local.')
        self._server.should_exit = True
        self._server_thread.join(timeout=15)
        if self._server_thread.is_alive():
            self._server.force_exit = True
            self._server_thread.join(timeout=5)

        self._server = None
        self._server_thread = None
        self._set_tooltip('Docs Local — servidor parado')

    def _check_server(self) -> None:
        if self._server_stopped_by_user:
            return
        if self._server_thread and self._server_thread.is_alive():
            return
        if time.monotonic() < self._next_restart_at:
            return

        if not self._start_server():
            LOGGER.warning(
                'Nova tentativa de inicialização agendada em %s segundos.',
                self._restart_delay,
            )

    def _check_update_schedule(self) -> None:
        if not getattr(sys, 'frozen', False) or time.monotonic() < self._next_update_check_at:
            return
        self._next_update_check_at = time.monotonic() + UPDATE_CHECK_INTERVAL_SECONDS
        self._start_update_check(manual=False)

    def _start_update_check(self, *, manual: bool) -> None:
        if not getattr(sys, 'frozen', False):
            if manual:
                self._user32.MessageBoxW(
                    self._window_handle,
                    'A verificação de atualizações está disponível na versão instalada do Docs Local.',
                    'Docs Local',
                    MB_ICONINFORMATION | MB_TOPMOST,
                )
            return
        if not self._update_lock.acquire(blocking=False):
            return
        threading.Thread(
            target=self._check_for_update,
            args=(manual,),
            name='docs-local-updater',
            daemon=True,
        ).start()

    def _check_for_update(self, manual: bool) -> None:
        try:
            release = updater.check_latest()
            if release is None:
                if manual:
                    self._user32.MessageBoxW(
                        self._window_handle,
                        f'O Docs Local {VERSION} já está atualizado.',
                        'Docs Local',
                        MB_ICONINFORMATION | MB_TOPMOST,
                    )
                return
            answer = self._user32.MessageBoxW(
                self._window_handle,
                f'A versão {release["version"]} está disponível. Deseja baixar e instalar agora?',
                'Atualização do Docs Local',
                MB_YESNO | MB_ICONINFORMATION | MB_TOPMOST,
            )
            if answer != IDYES:
                return
            staged = updater.download_update(release)
            updater.launch_update_helper(staged, Path(sys.executable), os.getpid())
            self._user32.PostMessageW(self._window_handle, UPDATE_SHUTDOWN_MESSAGE, 0, 0)
        except Exception as error:
            LOGGER.warning('Falha ao verificar ou instalar atualização: %s', error)
            if manual:
                self._user32.MessageBoxW(
                    self._window_handle,
                    f'Não foi possível atualizar o Docs Local.\n\n{error}',
                    'Atualização do Docs Local',
                    MB_ICONINFORMATION | MB_TOPMOST,
                )
        finally:
            self._update_lock.release()


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == '--apply-update':
        try:
            raise SystemExit(updater.apply_update_after_exit(int(sys.argv[2]), Path(sys.argv[3])))
        except ValueError:
            raise SystemExit(2)
    configure_logging()
    try:
        DocsLocalTray().run()
    except RuntimeError as error:
        LOGGER.info('%s', error)
    except Exception:
        LOGGER.exception('O ícone do Docs Local não pôde ser iniciado.')


if __name__ == '__main__':
    main()
