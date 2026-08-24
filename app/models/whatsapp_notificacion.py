from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text

from app.database import Base


class WhatsappNotificacion(Base):
    __tablename__ = "whatsapp_notificacion"
    __table_args__ = {"schema": "petalops"}

    idNotificacion = Column("id_notificacion", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, nullable=False, index=True)
    pedidoID = Column("pedido_id", BigInteger, nullable=False, index=True)
    clienteID = Column("cliente_id", BigInteger, nullable=True)
    entregaID = Column("entrega_id", BigInteger, nullable=True)
    canal = Column("canal", String(20), nullable=False)
    evento = Column("evento", String(40), nullable=False)
    telefonoDestino = Column("telefono_destino", String(30), nullable=True)
    templateName = Column("template_name", String(80), nullable=True)
    metaMessageId = Column("meta_message_id", String(120), nullable=True)
    status = Column("status", String(20), nullable=False)
    attempts = Column("attempts", Integer, nullable=False, default=0)
    nextAttemptAt = Column("next_attempt_at", DateTime, nullable=True)
    errorCode = Column("error_code", String(60), nullable=True)
    errorMessage = Column("error_message", Text, nullable=True)
    createdAt = Column("created_at", DateTime, nullable=False)
    sentAt = Column("sent_at", DateTime, nullable=True)
    deliveredAt = Column("delivered_at", DateTime, nullable=True)
    readAt = Column("read_at", DateTime, nullable=True)
    failedAt = Column("failed_at", DateTime, nullable=True)
