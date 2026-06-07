import logging
from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np
from sqlalchemy.orm import Session

from memoria.database.models import FaceDetection, FilePeople, FileTag, Person, Tag

log = logging.getLogger(__name__)

CLUSTER_THRESHOLD = 0.4   # max euclidean distance on normalised ArcFace vectors (~cosine distance)
MIN_CLUSTER_SIZE  = 2     # clusters smaller than this are marked as noise

# Matching is deliberately more lenient than clustering.
# Clustering wants tight, high-precision groups; matching wants to catch
# the same person across lighting/angle/expression variation.
# ArcFace on normalised vectors: dist 0.4 ≈ cos 0.92, dist 0.6 ≈ cos 0.82.
MATCH_THRESHOLD = 0.6


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

    # Track pairs added in this call to avoid duplicates when a file
    # contains multiple faces of the same person (session not yet flushed).
    added_pairs: set[tuple[int, int]] = set()

    for det in detections:
        det.person_id = person.id
        pair = (det.file_id, person.id)
        if pair in added_pairs:
            continue
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
            added_pairs.add(pair)

    session.commit()
    log.info(f"Assigned cluster {cluster_id} ({len(detections)} faces) to '{person_name}'")
    return person


def merge_clusters(session: Session, cluster_ids: list[int], person_name: str) -> Person:
    """Merge multiple clusters into one named person."""
    person = None
    for cluster_id in cluster_ids:
        person = assign_cluster_to_person(session, cluster_id, person_name)
    return person


def _ensure_tag(session: Session, label: str, file_id: int):
    """Create tag with *label* and link it to *file_id* if not already present."""
    tag = session.query(Tag).filter_by(label=label).first()
    if tag is None:
        tag = Tag(label=label)
        session.add(tag)
        session.flush()
    exists = session.query(FileTag).filter_by(file_id=file_id, tag_id=tag.id).first()
    if not exists:
        session.add(FileTag(file_id=file_id, tag_id=tag.id))


def _normalise(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1 if mat.ndim == 2 else None, keepdims=mat.ndim == 2)
    return mat / np.where(norms == 0, 1, norms)


def match_against_known_persons(
    session: Session,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """
    Compare every unassigned face detection against the embedding gallery of
    every known person.  Assigns person_id (and upserts FilePeople + tag) when
    the nearest-gallery distance is within MATCH_THRESHOLD.

    Returns stats dict: {matched, unmatched, people_checked}
    """
    def _prog(cur, tot, msg):
        if progress:
            progress(cur, tot, msg)
        else:
            log.info(f"[{cur}/{tot}] {msg}")

    # ── Build per-person embedding gallery ───────────────────────────────────
    all_persons = session.query(Person).all()
    if not all_persons:
        log.info("No named persons in DB — nothing to match against")
        return {"matched": 0, "unmatched": 0, "people_checked": 0}

    person_id_to_name = {p.id: p.name for p in all_persons}
    gallery: dict[int, np.ndarray] = {}   # person_id → (N, D) normalised array

    for person in all_persons:
        dets = (
            session.query(FaceDetection)
            .filter(FaceDetection.person_id == person.id,
                    FaceDetection.encoding_path.isnot(None))
            .all()
        )
        vecs = []
        for d in dets:
            enc = Path(d.encoding_path)
            if enc.exists():
                vecs.append(np.load(str(enc)))
            else:
                log.warning(f"Missing embedding file for detection {d.id}: {d.encoding_path}")

        if vecs:
            mat = _normalise(np.vstack(vecs).astype(np.float32))
            gallery[person.id] = mat
            log.info(f"Gallery — '{person.name}': {len(vecs)} embedding(s)")
        else:
            log.warning(
                f"Person '{person.name}' (id={person.id}) has no usable embeddings — "
                "they were either named without face-scanning or encoding files are missing. "
                "Re-scan this photo to rebuild embeddings."
            )

    if not gallery:
        log.warning(
            "No person has usable embeddings. "
            "Ensure photos are face-scanned before naming (Library → Re-index)."
        )
        return {"matched": 0, "unmatched": 0, "people_checked": len(all_persons)}

    # ── Load unassigned detections ────────────────────────────────────────────
    unassigned = (
        session.query(FaceDetection)
        .filter(FaceDetection.person_id.is_(None),
                FaceDetection.encoding_path.isnot(None))
        .all()
    )

    log.info(
        f"Matching {len(unassigned)} unassigned detection(s) against "
        f"{len(gallery)} known person(s) — threshold {MATCH_THRESHOLD}"
    )

    if not unassigned:
        log.info("No unassigned face detections to match")
        return {"matched": 0, "unmatched": 0, "people_checked": len(gallery)}

    total   = len(unassigned)
    matched = 0
    missing_files = 0

    # For diagnostics — track the distribution of best distances
    distances_seen: list[float] = []

    # Track per-file pairs already added this run (duplicate guard)
    added_pairs: set[tuple[int, int]] = set()

    for i, det in enumerate(unassigned):
        _prog(i + 1, total, f"Matching face {i + 1}/{total}…")

        enc = Path(det.encoding_path)
        if not enc.exists():
            missing_files += 1
            continue

        vec = _normalise(np.load(str(enc)).astype(np.float32).reshape(1, -1))[0]

        best_pid  = None
        best_dist = float("inf")

        for pid, gal in gallery.items():
            d = float(np.linalg.norm(gal - vec, axis=1).min())
            if d < best_dist:
                best_dist = d
                best_pid  = pid

        distances_seen.append(best_dist)

        if best_pid is not None and best_dist <= MATCH_THRESHOLD:
            det.person_id = best_pid
            pair = (det.file_id, best_pid)

            if pair not in added_pairs:
                fp = (
                    session.query(FilePeople)
                    .filter_by(file_id=det.file_id, person_id=best_pid)
                    .first()
                )
                if fp is None:
                    session.add(FilePeople(
                        file_id=det.file_id,
                        person_id=best_pid,
                        confidence_score=det.face_confidence,
                    ))
                _ensure_tag(session, person_id_to_name[best_pid], det.file_id)
                added_pairs.add(pair)

            matched += 1
            # Grow the gallery with confirmed matches so later detections benefit
            gallery[best_pid] = np.vstack([gallery[best_pid], vec])

    session.commit()

    unmatched = total - matched

    # Diagnostic summary — helps tune the threshold
    if distances_seen:
        arr = np.array(distances_seen)
        log.info(
            f"Distance stats over {len(arr)} faces — "
            f"min={arr.min():.3f}  median={float(np.median(arr)):.3f}  "
            f"max={arr.max():.3f}  "
            f"within threshold ({MATCH_THRESHOLD}): {int((arr <= MATCH_THRESHOLD).sum())}"
        )
    if missing_files:
        log.warning(f"{missing_files} detection(s) skipped — embedding file not found on disk")

    log.info(f"Matching complete: {matched} assigned, {unmatched} still unassigned")
    return {"matched": matched, "unmatched": unmatched, "people_checked": len(gallery)}


def audit_person_tags(
    session: Session,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """
    Ensure every photo that has a named person also has a tag matching
    that person's name.  Fills any gaps silently.
    Returns {"tags_added": N}.
    """
    from memoria.database.models import FilePeople, Person

    rows = (
        session.query(FilePeople.file_id, Person.name)
        .join(Person, Person.id == FilePeople.person_id)
        .all()
    )

    added = 0
    total = len(rows)
    for i, (file_id, name) in enumerate(rows):
        if progress:
            progress(i + 1, total, f"Auditing tags ({i + 1}/{total})…")
        existing_count = (
            session.query(FileTag)
            .join(Tag, Tag.id == FileTag.tag_id)
            .filter(FileTag.file_id == file_id, Tag.label == name)
            .count()
        )
        if existing_count == 0:
            _ensure_tag(session, name, file_id)
            added += 1

    if added:
        session.commit()
        log.info(f"Tag audit: added {added} missing person-name tag(s)")

    return {"tags_added": added}


def run_reassess(
    session: Session,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """
    Full re-assessment pipeline:
      1. Scan any photos not yet face-scanned.
      2. Match unassigned detections against known-person galleries.
      3. Re-cluster whatever is still unassigned.
    Returns a combined stats dict.
    """
    from memoria.faces.encoding import run_face_scan

    def _prog(cur, tot, msg):
        if progress:
            progress(cur, tot, msg)

    _prog(0, 4, "Step 1/4 — scanning unprocessed photos…")
    scan_stats = run_face_scan(session, progress=progress)

    _prog(1, 4, "Step 2/4 — matching faces to known people…")
    match_stats = match_against_known_persons(session, progress=progress)

    _prog(2, 4, "Step 3/4 — clustering remaining faces…")
    cluster_stats = run_clustering(session)

    _prog(3, 4, "Step 4/4 — auditing person-name tags…")
    tag_stats = audit_person_tags(session, progress=progress)

    _prog(4, 5, "Step 5/5 — syncing tags to file metadata…")
    from memoria.exif_writer import sync_all_tags
    exif_stats = sync_all_tags(session, progress=progress)

    _prog(5, 5, "Done.")
    return {**scan_stats, **match_stats, **cluster_stats, **tag_stats, **exif_stats}
