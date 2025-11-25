from typing import Generator, List, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from config import settings


def _clean_api_key(raw: str | None) -> str:
    """Trim whitespace/BOM that can invalidate otherwise-correct keys."""
    return (raw or "").strip().lstrip("\ufeff")


DEFAULT_GOOGLE_MAPS_API_KEY = settings.google_maps_api_key
DEFAULT_MAP_ID = settings.map_id

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="MapTMarkers"), name="static")

# --- Database setup (PostgreSQL) ---
SQLALCHEMY_DATABASE_URL = settings.database_url
engine = create_engine(SQLALCHEMY_DATABASE_URL, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    visit_status = Column(String, nullable=True)
    segment = Column(String, nullable=True)

    visits = relationship("VisitSchedule", back_populates="customer")


class VisitSchedule(Base):
    __tablename__ = "visit_schedules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    result = Column(String, nullable=True)
    detail = Column(String, nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)

    customer = relationship("Customer", back_populates="visits")


class MaptechUser(Base):
    __tablename__ = "maptech_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True)
    password = Column(String, nullable=False)
    transport_method = Column(String, nullable=True)
    route_origin = Column(String, nullable=True)
    saved_search_conditions = Column(String, nullable=True)
    marker_cluster_max_zoom = Column(Integer, nullable=True)
    zoom_setting = Column(Integer, nullable=True)
    origin_lng = Column(Float, nullable=True)
    origin_lat = Column(Float, nullable=True)
    nearby_distance_km = Column(Float, nullable=True)
    map_display_type_main = Column(String, nullable=True)
    map_display_type_adjust = Column(String, nullable=True)
    toll_usage = Column(String, nullable=True)
    visit_status = Column(String, nullable=True)
    past_visit_edit = Column(String, nullable=True)


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_if_empty() -> None:
    """Insert a couple of rows so map/GET endpoints return something on first run."""
    from datetime import datetime, timedelta

    db = SessionLocal()
    try:
        if db.query(Customer).count() == 0:
            c1 = Customer(
                name="東京本社ビル",
                address="東京都千代田区丸の内1-9-1",
                latitude=35.681236,
                longitude=139.767125,
                visit_status="未訪問",
                segment="法人",
            )
            c2 = Customer(
                name="新宿営業所",
                address="東京都新宿区西新宿2-8-1",
                latitude=35.689592,
                longitude=139.691833,
                visit_status="訪問済み",
                segment="法人",
            )
            db.add_all([c1, c2])
            db.commit()
        if db.query(VisitSchedule).count() == 0:
            now = datetime.utcnow()
            visit = VisitSchedule(
                name="定期訪問",
                start_at=now + timedelta(days=1),
                end_at=now + timedelta(days=1, hours=1),
                result=None,
                detail="次回の商談準備",
                customer_id=1,
            )
            db.add(visit)
            db.commit()
        if db.query(MaptechUser).count() == 0:
            demo_user = MaptechUser(
                username="demo",
                password="demo",
                transport_method="徒歩",
                route_origin="東京駅",
                saved_search_conditions="",
                marker_cluster_max_zoom=12,
                zoom_setting=13,
                origin_lng=139.767125,
                origin_lat=35.681236,
                nearby_distance_km=5,
                map_display_type_main="標準",
                map_display_type_adjust="登録・調整",
                toll_usage="利用する",
                visit_status="未訪問",
                past_visit_edit="不可",
            )
            db.add(demo_user)
            db.commit()
    finally:
        db.close()


# --- Pydantic schemas ---
class CustomerCreate(BaseModel):
    name: str
    address: str
    latitude: float
    longitude: float
    visit_status: Optional[str] = None
    segment: Optional[str] = None


class CustomerRead(CustomerCreate):
    id: int

    class Config:
        from_attributes = True


class VisitCreate(BaseModel):
    name: str
    start_at: str  # ISO8601
    end_at: str    # ISO8601
    result: Optional[str] = None
    detail: Optional[str] = None
    customer_id: Optional[int] = None


class VisitRead(BaseModel):
    id: int
    name: str
    start_at: str
    end_at: str
    result: Optional[str] = None
    detail: Optional[str] = None
    customer_id: Optional[int] = None

    class Config:
        from_attributes = True


class SearchFilter(BaseModel):
    field: str
    value: str


class SearchRequest(BaseModel):
    filters: List[SearchFilter] = []


def _parse_datetime(value: str):
    """Parse ISO8601 string to datetime; raises HTTP 400 on failure."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(value)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid datetime: {value}") from exc


def _get_current_user(request: Request, db):
    username = request.cookies.get("auth_user")
    if not username:
        return None
    return db.query(MaptechUser).filter(MaptechUser.username == username).first()


@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    error = request.query_params.get("error")
    msg = "ユーザー名またはパスワードが違います" if error else ""
    return templates.TemplateResponse("LoginPage.html", {"request": request, "error_message": msg})


@app.get("/LoginPage", response_class=HTMLResponse)
def login_page_alias(request: Request):
    error = request.query_params.get("error")
    msg = "ユーザー名またはパスワードが違います" if error else ""
    return templates.TemplateResponse("LoginPage.html", {"request": request, "error_message": msg})


@app.get("/MobileMapPage", response_class=HTMLResponse)
def mobile_map_page(request: Request, api_key: str | None = None):
    """
    Serve the mobile map page. Optional query param ?api_key=... can override the default key
    (handy for verifying keys). Sanitization avoids hidden BOM/whitespace issues.
    """
    username = request.cookies.get("auth_user")
    if not username:
        return RedirectResponse(url="/LoginPage", status_code=303)
    # Simple existence check for logged-in user
    with SessionLocal() as db:
        exists = db.query(MaptechUser.id).filter(MaptechUser.username == username).first()
        if not exists:
            return RedirectResponse(url="/LoginPage", status_code=303)

    key_to_use = _clean_api_key(api_key) if api_key else DEFAULT_GOOGLE_MAPS_API_KEY
    if not key_to_use:
        raise HTTPException(status_code=500, detail="Google Maps API key is missing.")
    return templates.TemplateResponse(
        "MapTMobileMapPage.html",
        {"request": request, "google_maps_api_key": key_to_use, "map_id": DEFAULT_MAP_ID},
    )


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), db=Depends(get_db)):
    user = (
        db.query(MaptechUser)
        .filter(MaptechUser.username == username, MaptechUser.password == password)
        .first()
    )
    if not user:
        return RedirectResponse(url="/LoginPage?error=1", status_code=303)
    resp = RedirectResponse(url="/MobileMapPage", status_code=303)
    resp.set_cookie("auth_user", username, httponly=True, max_age=60 * 60 * 8)
    return resp


@app.get("/api/markers")
def list_markers(db=Depends(get_db)):
    """Return customers as markers for the map."""
    customers = db.query(Customer).all()
    return [
        {"id": c.id, "title": c.name, "lat": c.latitude, "lng": c.longitude, "address": c.address}
        for c in customers
    ]


@app.get("/api/customers", response_model=List[CustomerRead])
def list_customers(db=Depends(get_db)):
    return db.query(Customer).order_by(Customer.id).all()


@app.post("/api/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db=Depends(get_db)):
    customer = Customer(**payload.dict())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@app.get("/api/visits", response_model=List[VisitRead])
def list_visits(db=Depends(get_db)):
    return db.query(VisitSchedule).order_by(VisitSchedule.start_at).all()


@app.post("/api/visits", response_model=VisitRead, status_code=status.HTTP_201_CREATED)
def create_visit(payload: VisitCreate, db=Depends(get_db)):
    visit = VisitSchedule(
        name=payload.name,
        start_at=_parse_datetime(payload.start_at),
        end_at=_parse_datetime(payload.end_at),
        result=payload.result,
        detail=payload.detail,
        customer_id=payload.customer_id,
    )
    db.add(visit)
    db.commit()
    db.refresh(visit)
    return visit


@app.get("/api/search/fields")
def get_search_fields():
    """Expose searchable fields for customers (visits excluded per request)."""
    customer_fields = [col.name for col in Customer.__table__.columns]
    return {"customers": customer_fields}


@app.post("/api/search/customers")
def search_customers(payload: SearchRequest, db=Depends(get_db)):
    """Search customers by provided filters; supports partial match for text, exact for numbers."""
    from sqlalchemy import String

    allowed = {col.name: getattr(Customer, col.name) for col in Customer.__table__.columns}
    query = db.query(Customer)
    for f in payload.filters or []:
        col = allowed.get(f.field)
        if not col or f.value is None or f.value == "":
            continue
        # Match type to decide filter
        if isinstance(col.type, (Float, Integer)):
            try:
                num = float(f.value) if isinstance(col.type, Float) else int(f.value)
            except Exception:
                continue
            query = query.filter(col == num)
        else:
            query = query.filter(col.ilike(f"%{f.value}%"))

    customers = query.all()
    return [
        {"id": c.id, "title": c.name, "lat": c.latitude, "lng": c.longitude, "address": c.address}
        for c in customers
    ]


@app.get("/api/customers/{customer_id}/detail")
def get_customer_detail(customer_id: int, db=Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    visits = (
        db.query(VisitSchedule)
        .filter(VisitSchedule.customer_id == customer_id)
        .order_by(VisitSchedule.start_at)
        .all()
    )

    def _visit_dict(v: VisitSchedule):
        return {
            "id": v.id,
            "name": v.name,
            "start_at": v.start_at.isoformat() if v.start_at else None,
            "end_at": v.end_at.isoformat() if v.end_at else None,
            "result": v.result,
            "detail": v.detail,
            "customer_id": v.customer_id,
        }

    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "address": customer.address,
            "latitude": customer.latitude,
            "longitude": customer.longitude,
            "visit_status": customer.visit_status,
            "segment": customer.segment,
        },
        "visits": [_visit_dict(v) for v in visits],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
