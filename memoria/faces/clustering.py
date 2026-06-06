import logging
from collections import Counter
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from memoria.database.models import FaceDetection, FilePeople, Person

log = logging.getLogger(__name__)

CLUSTER_THRESHOLD = 0.4   # max euclidean distance on normalised ArcFace vectors (~cosine distance)
MIN_CLUSTER_SIZE = 2       # clusters smaller than this are marked as noise


# ---------------------------------------------------------------------------
# Pure-numpy clustering (no scikit-learn / no compiled .pyd extensions)
# ---------------------------------------------------------------------------

def _cosine_normalize(X: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    return X / np.where(norms == 0, 1, norms)


def _union_find_cluster(X_norm: np.ndarray, threshold: float, min_size: int) -> np.ndarray:
    """
    Single-linkage connected-components clustering.
    Two faces are linked when their euclidean distance on unit-normalised
    vectors is <= threshold (equivalent to cosine similarity >= 1 - threshold²/2).

    Processes in batches of 1 000 rows to stay memory-efficient at 30 k+ faces.
    Returns an integer label array; -1 = noise (singleton or sub-min_size cluster).
    """
    n = len(X_norm)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    batch_size = 1_000
    for i in range(0, n, batch_size):
        batch = X_norm[i : i + batch_size]
        # dot product → cosine similarity → euclidean distance on unit sphere
        dots = batch @ X_norm.T
        dists = np.sqrt(np.maximum(0.0, 2.0 - 2.0 * dots))
        for bi in range(len(batch)):
            gi = i + bi
            for j in np.where(dists[bi] <= threshold)[0]:
                if int(j) != gi:
                    union(gi, int(j))

    # Map roots → compact labels
    root_to_label: dict[int, int] = {}
    next_label = 0
    raw_labels = np.empty(n, dtype=np.int32)
    for i in range(n):
        root = find(i)
        if root not in root_to_label:
            root_to_label[root] = next_label
            next_label += 1
        raw_labels[i] = root_to_label[root]

    # Suppress clusters smaller than min_size → noise (-1)
    counts = Counter(raw_labels.tolist())
    noise_labels = {lab for lab, cnt in counts.items() if cnt < min_size}
    final = np.where(np.isin(raw_labels, list(noise_labels)), -1, raw_labels)

    # Renumber surviving clusters 0, 1, 2, …
    surviving = sorted(set(final.tolist()) - {-1})
    remap = {old: new for new, old in enumerate(surviving)}
    return np.array([remap[v] if v != -1 else -1 for v in final], dtype=np.int32)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _load_embeddings(detections: list[FaceDetection]) -> tuple[np.ndarray | None, list[int]]:
    """
    Load .npy embeddings for the given detections.
    Returns (embeddings array, list of detection indices that loaded successfully).
    """
    vectors, valid_indices = [], []
    for idx, det in enumerate(detections):
        if not det.encoding_path or not Path(det.encoding_path).exists():
            log.warning(f"Missing encoding file for detection {det.id}")
            continue
        vectors.append(np.load(det.encoding_path))
        valid_indices.append(idx)
    if not vectors:
        return None, []
    return np.vstack(vectors), valid_indices


def run_clustering(session: Session) -> dict:
    """
    Cluster all unassigned face detections.
    Assigns cluster_id to each detection. Returns stats dict.
    """
    unassigned = (
        session.query(FaceDetection)
        .filter(FaceDetection.person_id.is_(None))
        .all()
    )

    if len(unassigned) < 2:
        log.info("Not enough unassigned faces to cluster")
        return {"clusters": 0, "noise": 0, "faces": len(unassigned)}

    log.info(f"Clustering {len(unassigned)} unassigned face detections…")

    embeddings, valid_indices = _load_embeddings(unassigned)
    if embeddings is None:
        return {"clusters": 0, "noise": 0, "faces": 0}

    X_norm = _cosine_normalize(embeddings)
    labels = _union_find_cluster(X_norm, CLUSTER_THRESHOLD, MIN_CLUSTER_SIZE)

    # Write cluster_id back — only for detections whose embedding loaded
    for list_pos, det_idx in enumerate(valid_indices):
        unassigned[det_idx].cluster_id = int(labels[list_pos])

    session.commit()

    n_clusters = int(np.sum(labels >= 0))  # faces assigned to a real cluster
    n_noise = int(np.sum(labels == -1))
    unique_clusters = len(set(labels.tolist()) - {-1})
    log.info(f"Clustering complete: {unique_clusters} cluster(s), {n_noise} noise face(s)")
    return {"clusters": unique_clusters, "noise": n_noise, "faces": len(unassigned)}


def get_clusters_for_review(session: Session) -> list[dict]:
    """
    Return clusters ready for naming in the UI.
    Each entry: {cluster_id, face_count, sample_detections (up to 5), person_id}
    """
    from sqlalchemy import func

    rows = (
        session.query(FaceDetection.cluster_id, func.count(FaceDetection.id))
        .filter(FaceDetection.cluster_id.isnot(None), FaceDetection.cluster_id >= 0)
        .group_by(FaceDetection.cluster_id)
        .order_by(func.count(FaceDetection.id).desc())
        .all()
    )

    clusters = []
    for cluster_id, count in rows:
        samples = (
            session.query(FaceDetection)
            .filter(FaceDetection.cluster_id == cluster_id)
            .limit(5)
            .all()
        )
        clusters.append({
            "cluster_id": cluster_id,
            "face_count": count,
            "sample_detections": samples,
            "person_id": samples[0].person_id if samples else None,
        })
    return clusters


def assign_cluster_to_person(
    session: Session,
    cluster_id: int,
    person_name: str,
) -> Person:
    """Assign all detections in a cluster to a named person, creating them if needed."""
    person = session.query(Person).filter_by(name=person_name).first()
    if person is None:
        person = Person(name=person_name)
        session.add(person)
        session.flush()

    detections = (
        session.query(FaceDetection)
        .filter(FaceDetection.cluster_id == cluster_id)
        .all()
    )

    for det in detections:
        det.person_id = person.id
        existing = (
            session.query(FilePeople)
            .filter_by(file_id=det.file_id, person_id=person.id)
            .first()
        )
        if existing is None:
            session.add(FilePeople(
                file_id=det.file_id,
                person_id=person.id,
                confidence_score=det.face_confidence,
            ))

    session.commit()
    log.info(f"Assigned cluster {cluster_id} ({len(detections)} faces) to '{person_name}'")
    return person


def merge_clusters(session: Session, cluster_ids: list[int], person_name: str) -> Person:
    """Merge multiple clusters into one named person."""
    person = None
    for cluster_id in cluster_ids:
        person = assign_cluster_to_person(session, cluster_id, person_name)
    return person
