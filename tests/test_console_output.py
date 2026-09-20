import errno
import io
import unittest
from unittest.mock import Mock, patch

from console_output import write_console


class ConsoleOutputTests(unittest.TestCase):
    def test_healthy_console_keeps_text_and_flushes(self):
        stream = Mock(wraps=io.StringIO())
        with patch("console_output.sys.stdout", stream):
            self.assertTrue(write_console("中文\n"))
        stream.write.assert_called_once_with("中文\n")
        stream.flush.assert_called_once_with()

    def test_unavailable_console_is_optional(self):
        closed = io.StringIO()
        closed.close()
        for stream in (None, closed):
            with self.subTest(stream=stream), patch("console_output.sys.stdout", stream):
                self.assertFalse(write_console("message\n"))

    def test_write_and_flush_handle_errors_are_contained(self):
        for operation in ("write", "flush"):
            for code in (errno.EINVAL, errno.EBADF, errno.EPIPE):
                with self.subTest(operation=operation, code=code):
                    stream = Mock(encoding="utf-8")
                    getattr(stream, operation).side_effect = OSError(code, "broken handle")
                    with patch("console_output.sys.stdout", stream):
                        self.assertFalse(write_console("message\n"))
                        self.assertFalse(write_console("next message\n"))
                    stream.write.assert_called_once_with("message\n")
                    stream.close.assert_called_once_with()

    def test_failed_close_cannot_reactivate_stdout_or_mask_the_failure(self):
        stream = Mock(encoding="utf-8")
        stream.flush.side_effect = OSError(errno.EINVAL, "Invalid argument")
        stream.close.side_effect = OSError(errno.EINVAL, "Invalid argument")
        with patch("console_output.sys.stdout", stream):
            self.assertFalse(write_console("message\n"))
            self.assertFalse(write_console("next\n"))
        stream.write.assert_called_once_with("message\n")
        stream.close.assert_called_once_with()

    def test_encoding_fallback_cannot_raise_a_second_handle_error(self):
        stream = Mock(encoding="ascii")
        stream.write.side_effect = [UnicodeEncodeError("ascii", "中", 0, 1, "unsupported"),
                                    OSError(errno.EINVAL, "Invalid argument")]
        with patch("console_output.sys.stdout", stream):
            self.assertFalse(write_console("中\n"))
        self.assertEqual([call.args[0] for call in stream.write.call_args_list], ["中\n", "?\n"])

    def test_unexpected_programming_errors_are_not_hidden(self):
        stream = Mock()
        stream.write.side_effect = RuntimeError("unexpected failure")
        with patch("console_output.sys.stdout", stream), self.assertRaises(RuntimeError):
            write_console("test")
