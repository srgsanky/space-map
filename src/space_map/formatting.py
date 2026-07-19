_MB = 1024**2
_GB = 1024**3
_TB = 1024**4


def format_size(size: int) -> str:
    if size >= _TB:
        return f"{size / _TB:.1f} TB"
    if size >= _GB:
        return f"{size / _GB:.1f} GB"
    return f"{size / _MB:.1f} MB"


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
