import re
from src.utils.logger import setup_logger


def test_logger_format(capsys):
    logger = setup_logger('test_logger')
    logger.info('SerializeToFile result[1]')
    out, err = capsys.readouterr()
    # Expect format: [YYYY.MM.DD HH:MM:SS.mmm] {0xHEX} I Message
    pattern = (
        r"^\[\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] "
        r"\{0x[0-9a-f]+\} I SerializeToFile result\[1\]$"
    )
    # Capture only the last non-empty line
    # Note: StreamHandler prints to stderr by default
    stream = err if err else out
    lines = [line for line in stream.splitlines() if line.strip()]
    last = lines[-1] if lines else ""
    assert re.match(pattern, last), f"Unexpected log format: {last}"
