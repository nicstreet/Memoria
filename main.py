import logging
import sys

from memoria.config import LOG_PATH
from memoria.database.db import get_engine, get_session
from memoria.database.models import WatchedFolder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def main():
    log.info("Memoria starting up")

    # Initialise DB (creates tables if they don't exist)
    engine = get_engine()
    log.info(f"Database ready at {engine.url}")

    # CLI helper: python main.py add-folder "C:\path\to\photos"
    if len(sys.argv) == 3 and sys.argv[1] == "add-folder":
        folder = sys.argv[2]
        session = get_session()
        try:
            existing = session.query(WatchedFolder).filter_by(path=folder).first()
            if existing:
                log.info(f"Folder already watched: {folder}")
            else:
                session.add(WatchedFolder(path=folder))
                session.commit()
                log.info(f"Added watched folder: {folder}")
        finally:
            session.close()
        return

    # CLI helper: python main.py index
    if len(sys.argv) == 2 and sys.argv[1] == "index":
        from memoria.indexer.scanner import run_index
        session = get_session()
        try:
            stats = run_index(session)
        finally:
            session.close()
        log.info(f"Indexing stats: {stats}")
        return

    # CLI helper: python main.py scan-faces
    if len(sys.argv) == 2 and sys.argv[1] == "scan-faces":
        from memoria.faces.encoding import run_face_scan
        session = get_session()
        try:
            stats = run_face_scan(session)
        finally:
            session.close()
        log.info(f"Face scan stats: {stats}")
        return

    # CLI helper: python main.py cluster-faces
    if len(sys.argv) == 2 and sys.argv[1] == "cluster-faces":
        from memoria.faces.clustering import run_clustering, get_clusters_for_review
        session = get_session()
        try:
            stats = run_clustering(session)
            log.info(f"Clustering stats: {stats}")
            clusters = get_clusters_for_review(session)
            log.info(f"{len(clusters)} cluster(s) ready for review in the UI")
            for c in clusters[:10]:  # preview first 10
                log.info(f"  Cluster {c['cluster_id']}: {c['face_count']} face(s)")
        finally:
            session.close()
        return

    # Launch the UI
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QPalette, QColor
    from memoria.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Memoria")

    # Force dark palette at OS level as a base
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#d4d4d4"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#252526"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#d4d4d4"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#3a3a3a"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#d4d4d4"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#7c6af7"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
