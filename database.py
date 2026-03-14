from sqlalchemy import Column, Integer, String, Float, BigInteger, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from config import DATABASE_URL, DISTRICTS

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    role = Column(String, nullable=False)  # 'client', 'installer'
    name = Column(String)
    phone = Column(String)
    username = Column(String)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class District(Base):
    __tablename__ = 'districts'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

class Request(Base):
    __tablename__ = 'requests'
    
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('users.id'))
    description = Column(Text)
    photo_file_id = Column(String)
    address = Column(String)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_address = Column(String, nullable=True)
    contact_phone = Column(String)
    district_id = Column(Integer, ForeignKey('districts.id'))
    status = Column(String, default='new')
    installer_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # relationships
    client = relationship("User", foreign_keys=[client_id])
    installer = relationship("User", foreign_keys=[installer_id])
    district = relationship("District")

class Refusal(Base):
    __tablename__ = 'refusals'
    
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('requests.id'))
    installer_id = Column(Integer, ForeignKey('users.id'))
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class GroupMessage(Base):
    __tablename__ = 'group_messages'
    
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('requests.id'))
    group_chat_id = Column(BigInteger)
    message_id = Column(Integer)

class GeocodeCache(Base):
    __tablename__ = 'geocode_cache'
    
    id = Column(Integer, primary_key=True)
    latitude = Column(Float)
    longitude = Column(Float)
    address = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (UniqueConstraint('latitude', 'longitude', name='unique_coords'),)

# Создание движка базы данных
engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Добавляем районы, если их нет
    from sqlalchemy import select
    async with async_session() as session:
        for district_name in DISTRICTS:
            result = await session.execute(
                select(District).where(District.name == district_name)
            )
            if not result.scalar_one_or_none():
                session.add(District(name=district_name))
        await session.commit()
        print(f"✅ Добавлены районы: {DISTRICTS}")