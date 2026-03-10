from sqlalchemy import Column, BigInteger, String, DateTime, Text

from app.database import Base


class UsuarioAuditoria(Base):
    __tablename__ = "UsuarioAuditoria"

    idAudit = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, nullable=False)
    actorUserID = Column(BigInteger, nullable=False)
    actorLogin = Column(String(80), nullable=False)
    accion = Column(String(60), nullable=False)
    targetUserID = Column(BigInteger, nullable=False)
    targetLogin = Column(String(80), nullable=False)
    detalleJSON = Column(Text)
    createdAt = Column(DateTime, nullable=False)
