"""
reports/csv_exporter.py
Exporta el historial de operaciones a CSV/Excel.
TODO: añadir exportación a Excel con openpyxl.
"""
import csv
import io
from data.trade_log import get_trades
from logs.logger import get_logger

logger = get_logger(__name__)

def export_csv() -> str:
    """Exporta todas las operaciones a CSV como string."""
    trades = get_trades()
    if not trades:
        return ""

    output  = io.StringIO()
    writer  = csv.DictWriter(output, fieldnames=trades[0].keys())
    writer.writeheader()
    writer.writerows(trades)
    logger.info(f"📊 CSV exportado: {len(trades)} operaciones")
    return output.getvalue()

def export_csv_file(path: str):
    """Guarda el CSV en un archivo."""
    content = export_csv()
    if content:
        with open(path, "w") as f:
            f.write(content)
        logger.info(f"💾 CSV guardado en: {path}")
