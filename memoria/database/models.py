from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class File(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filepath = Column(Text, unique=True, nullable=False)
    filename = Column(Text, nullable=False)
    file_type = Column(Text, nullable=False)          # "photo" | "video"
    size_bytes = Column(Integer)
    file_modified_at = Column(DateTime)               # OS mtime — drives incremental re-index
    created_at = Column(DateTime)                     # OS ctime
    indexed_at = Column(DateTime, default=datetime.utcnow)
    face_scanned_at = Column(DateTime)                   # null = not yet face-scanned
    renamed = Column(Boolean, default=False, nullable=False, server_default="0")

    metadata_ = relationship(
        "Metadata", back_populates="file", uselist=False, cascade="all, delete-orphan"
    )
    file_people = relationship("FilePeople", back_populates="file", cascade="all, delete-orphan")
    file_tags = relationship("FileTag", back_populates="file", cascade="all, delete-orphan")
    duplicates_as_a = relationship(
        "Duplicate", foreign_keys="Duplicate.file_id_a", cascade="all, delete-orphan"
    )
    duplicates_as_b = relationship(
        "Duplicate", foreign_keys="Duplicate.file_id_b", cascade="all, delete-orphan"
    )
    face_detections = relationship(
        "FaceDetection", back_populates="file", cascade="all, delete-orphan"
    )


class Metadata(Base):
    __tablename__ = "metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, unique=True)
    date_taken = Column(DateTime)
    gps_lat = Column(Float)
    gps_lon = Column(Float)
    location_label = Column(Text)
    camera_make = Column(Text)
    camera_model = Column(Text)
    width = Column(Integer)
    height = Column(Integer)
    duration_seconds = Column(Float)                  # videos only
    phash = Column(Text)                              # imagehash hex string
    title = Column(Text)                              # user-set title
    subject = Column(Text)                            # user-set subject

    file = relationship("File", back_populates="metadata_")


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    face_encoding_path = Column(Text)                 # path to .npy under FACE_ENCODINGS_DIR
    created_at = Column(DateTime, default=datetime.utcnow)

    file_people = relationship("FilePeople", back_populates="person", cascade="all, delete-orphan")


class FilePeople(Base):
    __tablename__ = "file_people"

    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), primary_key=True)
    person_id = Column(Integer, ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    confidence_score = Column(Float)                  # DeepFace distance (lower = more confident)

    file = relationship("File", back_populates="file_people")
    person = relationship("Person", back_populates="file_people")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(Text, unique=True, nullable=False)

    file_tags = relationship("FileTag", back_populates="tag", cascade="all, delete-orphan")


class FileTag(Base):
    __tablename__ = "file_tags"

    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)

    file = relationship("File", back_populates="file_tags")
    tag = relationship("Tag", back_populates="file_tags")


class Duplicate(Base):
    __tablename__ = "duplicates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id_a = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    file_id_b = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    hash_distance = Column(Integer, nullable=False)   # imagehash hamming distance
    reviewed = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("file_id_a", "file_id_b", name="uq_duplicate_pair"),
        # Application must always store pairs with file_id_a < file_id_b
    )


class FaceDetection(Base):
    """One detected face within a photo. May or may not be assigned to a Person."""
    __tablename__ = "face_detections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    encoding_path = Column(Text)                        # path to .npy embedding vector
    bbox_x = Column(Integer)                            # bounding box pixels
    bbox_y = Column(Integer)
    bbox_w = Column(Integer)
    bbox_h = Column(Integer)
    face_confidence = Column(Float)                     # detector confidence
    person_id = Column(Integer, ForeignKey("people.id", ondelete="SET NULL"), nullable=True)
    cluster_id = Column(Integer)                        # temporary cluster label from DBSCAN

    file = relationship("File", back_populates="face_detections")
    person = relationship("Person")


class EditLog(Base):
    """Audit trail of metadata changes and AI actions.

    User edits:  source='user', saved=False until written to EXIF.
    AI actions:  source='ai',   ai_confirmed=None until user confirms/rejects.
    """
    __tablename__ = "edit_log"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    timestamp    = Column(DateTime, default=datetime.utcnow)
    file_id      = Column(Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True)
    filename     = Column(Text)                          # denormalized — for display
    filepath     = Column(Text)                          # denormalized — for EXIF write
    action_type  = Column(Text, nullable=False)          # "title" | "subject" | "tag_add" | "tag_remove"
                                                         # | "face_assign" | "rotate" | "rename"
    old_value    = Column(Text, nullable=True)
    new_value    = Column(Text, nullable=True)
    source       = Column(Text, default="user")          # "user" | "ai"
    saved        = Column(Boolean, default=False)        # True = written to EXIF
    ai_confirmed = Column(Boolean, nullable=True)        # None=not reviewed, True=correct, False=wrong

    file = relationship("File", foreign_keys=[file_id])


class WatchedFolder(Base):
    __tablename__ = "watched_folders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(Text, unique=True, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow)


class SubjectCategory(Base):
    __tablename__ = "subject_categories"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(Text, unique=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    subjects = relationship(
        "Subject", back_populates="category",
        cascade="all, delete-orphan",
        order_by="Subject.sort_order",
    )


class Subject(Base):
    __tablename__ = "subjects"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer, ForeignKey("subject_categories.id", ondelete="CASCADE"),
                         nullable=False)
    name        = Column(Text, nullable=False)
    sort_order  = Column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("category_id", "name", name="uq_subject_per_category"),
    )

    category = relationship("SubjectCategory", back_populates="subjects")
