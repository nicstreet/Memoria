"""
Phase 3 — Face Recognition Pipeline
Entry point that ties encoding + clustering together.
"""
from memoria.faces.encoding import run_face_scan
from memoria.faces.clustering import run_clustering, get_clusters_for_review, assign_cluster_to_person


def run_full_pipeline(session, progress=None) -> dict:
    """Run face scan then cluster. Returns combined stats."""
    scan_stats = run_face_scan(session, progress=progress)
    cluster_stats = run_clustering(session)
    return {**scan_stats, **cluster_stats}
