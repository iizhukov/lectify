from datetime import datetime
from sqlalchemy import create_engine, Column, String, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship


DATABASE_URL = "sqlite:///data/student_bot.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class DBFile(Base):
    __tablename__ = "files"

    id = Column(String, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    language = Column(String, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    nodes = relationship("DBWorkflowNode", back_populates="file", cascade="all, delete-orphan")
    workflows = relationship("DBWorkflow", back_populates="file", cascade="all, delete-orphan")


class DBWorkflow(Base):
    __tablename__ = "workflows"

    id = Column(String, primary_key=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    final_artifact_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(String, nullable=True)

    file = relationship("DBFile", back_populates="workflows")


class DBWorkflowNode(Base):
    __tablename__ = "workflow_nodes"

    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), primary_key=True)
    node_id = Column(String, primary_key=True)
    node_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    message = Column(String, nullable=True)
    artifact_path = Column(String, nullable=True)
    started_at = Column(String, nullable=True)
    ended_at = Column(String, nullable=True)

    file = relationship("DBFile", back_populates="nodes")


def init_sqlalchemy_db():
    Base.metadata.create_all(bind=engine)
