import math
from typing import Generator, List, Optional

from fastapi import Body, Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from urllib.parse import quote

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, create_engine
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
    end_at = Column(DateTime, nullable=True)
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
    zoom_setting = Column(String, nullable=True)
    origin_lng = Column(Float, nullable=True)
    origin_lat = Column(Float, nullable=True)
    nearby_distance_km = Column(Float, nullable=True)
    map_display_type_main = Column(String, nullable=True)
    map_display_type_adjust = Column(String, nullable=True)
    toll_usage = Column(String, nullable=True)
    visit_status = Column(String, nullable=True)
    past_visit_edit = Column(String, nullable=True)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True)
    password = Column(String, nullable=False)


class OrgDefaultSetting(Base):
    __tablename__ = "org_default_setting"

    id = Column(Integer, primary_key=True, index=True)
    search_limit = Column(Integer, nullable=True)
    nearby_distance_km = Column(Float, nullable=True)
    entry_exit_interval = Column(String, nullable=True)
    enable_area = Column(Boolean, nullable=False, default=False)
    enable_group = Column(Boolean, nullable=False, default=False)


class MarkerColorSetting(Base):
    __tablename__ = "marker_color_setting"

    id = Column(Integer, primary_key=True, index=True)
    priority = Column(Integer, nullable=True)
    target = Column(String, nullable=True)
    field_name = Column(String, nullable=True)
    match_value = Column(String, nullable=True)
    match_condition = Column(String, nullable=True)
    color = Column(String, nullable=True)
    marker_style = Column(String, nullable=True)


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
                zoom_setting="オートフォーカス",
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
        if db.query(AdminUser).count() == 0:
            admin_user = AdminUser(username="admin", password="admin")
            db.add(admin_user)
            db.commit()
        if db.query(OrgDefaultSetting).count() == 0:
            defaults = OrgDefaultSetting(
                search_limit=10000,
                nearby_distance_km=3.0,
                entry_exit_interval="30分間隔",
                enable_area=False,
                enable_group=False,
            )
            db.add(defaults)
            db.commit()
        if db.query(MarkerColorSetting).count() == 0:
            sample_colors = [
                {"priority": 1, "target": "顧客情報", "field_name": "address", "match_value": "さいたま市", "match_condition": "含む", "color": "#ffff00", "marker_style": "家"},
                {"priority": 2, "target": "顧客情報", "field_name": "address", "match_value": "茨城県", "match_condition": "一致する", "color": "#cc6633", "marker_style": ""},
                {"priority": 3, "target": "顧客情報", "field_name": "address", "match_value": "東京都", "match_condition": "含まない", "color": "#0033cc", "marker_style": ""},
                {"priority": 4, "target": "顧客情報", "field_name": "address", "match_value": "栃木県", "match_condition": "一致しない", "color": "#f55fcd", "marker_style": ""},
                {"priority": 5, "target": "訪問予定", "field_name": "result", "match_value": "無効", "match_condition": "一致する", "color": "#cccccc", "marker_style": ""},
                {"priority": 6, "target": "訪問予定", "field_name": "result", "match_value": "留守", "match_condition": "一致する", "color": "#cccccc", "marker_style": ""},
                {"priority": 7, "target": "訪問予定", "field_name": "result", "match_value": "オーダー", "match_condition": "一致する", "color": "#00cc00", "marker_style": ""},
            ]
            for row in sample_colors:
                db.add(MarkerColorSetting(**row))
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
    start_at: Optional[str] = None  # ISO8601
    end_at: Optional[str] = None    # ISO8601
    result: Optional[str] = None
    detail: Optional[str] = None
    customer_id: Optional[int] = None


class VisitRead(BaseModel):
    id: int
    name: str
    start_at: Optional[str] = None
    end_at: Optional[str] = None
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


class MaptechUserSettings(BaseModel):
    transport_method: Optional[str] = None
    route_origin: Optional[str] = None
    map_display_type_main: Optional[str] = None
    zoom_setting: Optional[str] = None
    nearby_distance_km: Optional[float] = None
    marker_cluster_max_zoom: Optional[int] = None
    toll_usage: Optional[str] = None


class MarkerColorRow(BaseModel):
    id: Optional[int] = None
    priority: Optional[int] = None
    target: Optional[str] = None
    field_name: Optional[str] = None
    match_value: Optional[str] = None
    match_condition: Optional[str] = None
    color: Optional[str] = None
    marker_style: Optional[str] = None


def _parse_datetime(value: str):
    """Parse ISO8601 string to datetime; empty/None returns None."""
    from datetime import datetime

    if value in (None, "", "null"):
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid datetime: {value}") from exc


def _get_current_user(request: Request, db):
    username = request.cookies.get("auth_user")
    if not username:
        return None
    return db.query(MaptechUser).filter(MaptechUser.username == username).first()


def _get_current_admin(request: Request, db):
    username = request.cookies.get("admin_auth_user")
    if not username:
        return None
    return db.query(AdminUser).filter(AdminUser.username == username).first()


def _get_org_default_setting(db):
    setting = db.query(OrgDefaultSetting).first()
    if setting:
        return setting
    setting = OrgDefaultSetting(
        search_limit=10000,
        nearby_distance_km=3.0,
        entry_exit_interval="30分間隔",
        enable_area=False,
        enable_group=False,
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


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


@app.get("/AdminLogin", response_class=HTMLResponse)
def admin_login_page(request: Request):
    error = request.query_params.get("error")
    msg = "ユーザー名またはパスワードが違います" if error else ""
    return templates.TemplateResponse("AdminLoginPage.html", {"request": request, "error_message": msg})


@app.get("/AdminSettings", response_class=HTMLResponse)
def admin_settings_page(request: Request, db=Depends(get_db)):
    admin = _get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/AdminLogin", status_code=303)
    setting = _get_org_default_setting(db)
    success_msg = "保存しました" if request.query_params.get("success") else ""
    error_msg = request.query_params.get("error") or ""
    marker_colors = (
        db.query(MarkerColorSetting)
        .order_by(MarkerColorSetting.priority.nulls_last(), MarkerColorSetting.id)
        .all()
    )
    maptech_users = db.query(MaptechUser).order_by(MaptechUser.id).all()
    users_payload = [
        {
            "id": u.id,
            "username": u.username,
            "password": u.password,
            "transport_method": u.transport_method,
            "route_origin": u.route_origin,
            "saved_search_conditions": u.saved_search_conditions,
            "marker_cluster_max_zoom": u.marker_cluster_max_zoom,
            "zoom_setting": u.zoom_setting,
            "origin_lng": u.origin_lng,
            "origin_lat": u.origin_lat,
            "nearby_distance_km": u.nearby_distance_km,
            "map_display_type_main": u.map_display_type_main,
            "map_display_type_adjust": u.map_display_type_adjust,
            "toll_usage": u.toll_usage,
            "visit_status": u.visit_status,
            "past_visit_edit": u.past_visit_edit,
        }
        for u in maptech_users
    ]
    marker_colors_payload = [
        {
            "id": mc.id,
            "priority": mc.priority,
            "target": mc.target,
            "field_name": mc.field_name,
            "match_value": mc.match_value,
            "match_condition": mc.match_condition,
            "color": mc.color,
            "marker_style": mc.marker_style,
        }
        for mc in marker_colors
    ]
    return templates.TemplateResponse(
        "AdminSettingsPage.html",
        {
            "request": request,
            "admin_username": admin.username,
            "setting": setting,
            "success_message": success_msg,
            "error_message": error_msg,
            "marker_colors": marker_colors_payload,
            "maptech_users": users_payload,
        },
    )

@app.post("/AdminSettings")
def update_admin_settings(
    request: Request,
    db=Depends(get_db),
    search_limit: str = Form(None),
    nearby_distance_km: str = Form(None),
    entry_exit_interval: str = Form("15分間隔"),
    enable_area: Optional[str] = Form(None),
    enable_group: Optional[str] = Form(None),
):
    admin = _get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/AdminLogin", status_code=303)

    def _parse_int(val: str | None) -> Optional[int] | str:
        if val in (None, ""):
            return None
        try:
            return int(val)
        except Exception:
            return "検索件数上限は数値で入力してください"

    def _parse_float(val: str | None) -> Optional[float] | str:
        if val in (None, ""):
            return None
        try:
            return float(val)
        except Exception:
            return "周辺座標取得距離は数値で入力してください"

    allowed_intervals = {"10分間隔", "15分間隔", "30分間隔"}
    interval_to_use = entry_exit_interval if entry_exit_interval in allowed_intervals else "15分間隔"

    parsed_limit = _parse_int(search_limit)
    if isinstance(parsed_limit, str):
        return RedirectResponse(url=f"/AdminSettings?error={quote(parsed_limit)}", status_code=303)

    parsed_distance = _parse_float(nearby_distance_km)
    if isinstance(parsed_distance, str):
        return RedirectResponse(url=f"/AdminSettings?error={quote(parsed_distance)}", status_code=303)

    setting = _get_org_default_setting(db)
    setting.search_limit = parsed_limit
    setting.nearby_distance_km = parsed_distance
    setting.entry_exit_interval = interval_to_use
    setting.enable_area = enable_area is not None
    setting.enable_group = enable_group is not None
    db.commit()
    db.refresh(setting)

    return RedirectResponse(url="/AdminSettings?success=1", status_code=303)


@app.post("/admin/marker-colors")
def save_marker_colors(
    request: Request,
    payload: dict = Body(...),
    db=Depends(get_db),
):
    admin = _get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    rows_data = payload.get("rows") or []
    parsed_rows: List[MarkerColorRow] = []
    for row in rows_data:
        try:
            parsed_rows.append(MarkerColorRow(**row))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid payload") from exc

    try:
        db.query(MarkerColorSetting).delete()
        db.commit()
        to_save = []
        for idx, r in enumerate(parsed_rows):
            to_save.append(
                MarkerColorSetting(
                    priority=r.priority or idx + 1,
                    target=r.target,
                    field_name=r.field_name,
                    match_value=r.match_value,
                    match_condition=r.match_condition,
                    color=r.color,
                    marker_style=r.marker_style,
                )
            )
        db.add_all(to_save)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail="保存に失敗しました") from exc

    return {"status": "ok"}


@app.post("/admin/users")
def save_maptech_users(
    request: Request,
    payload: dict = Body(...),
    db=Depends(get_db),
):
    admin = _get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    def _to_int(val):
        if val in (None, "", "null"):
            return None
        try:
            return int(val)
        except Exception:
            return None

    def _to_float(val):
        if val in (None, "", "null"):
            return None
        try:
            return float(val)
        except Exception:
            return None

    rows = payload.get("rows") or []
    try:
        db.query(MaptechUser).delete()
        db.commit()
        to_add = []
        for r in rows:
            username = (r.get("username") or "").strip()
            password = (r.get("password") or "").strip()
            if not username or not password:
                continue
            to_add.append(
                MaptechUser(
                    username=username,
                    password=password,
                    transport_method=r.get("transport_method"),
                    route_origin=r.get("route_origin"),
                    saved_search_conditions=r.get("saved_search_conditions"),
                    marker_cluster_max_zoom=_to_int(r.get("marker_cluster_max_zoom")),
                    zoom_setting=r.get("zoom_setting"),
                    origin_lng=_to_float(r.get("origin_lng")),
                    origin_lat=_to_float(r.get("origin_lat")),
                    nearby_distance_km=_to_float(r.get("nearby_distance_km")),
                    map_display_type_main=r.get("map_display_type_main"),
                    map_display_type_adjust=r.get("map_display_type_adjust"),
                    toll_usage=r.get("toll_usage"),
                    visit_status=r.get("visit_status"),
                    past_visit_edit=r.get("past_visit_edit"),
                )
            )
        if to_add:
            db.add_all(to_add)
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail="ユーザ保存に失敗しました") from exc

    return {"status": "ok"}


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


@app.post("/admin/login")
def admin_login(username: str = Form(...), password: str = Form(...), db=Depends(get_db)):
    admin = (
        db.query(AdminUser)
        .filter(AdminUser.username == username, AdminUser.password == password)
        .first()
    )
    if not admin:
        return RedirectResponse(url="/AdminLogin?error=1", status_code=303)
    resp = RedirectResponse(url="/AdminSettings", status_code=303)
    resp.set_cookie("admin_auth_user", username, httponly=True, max_age=60 * 60 * 8)
    return resp


@app.get("/api/markers")
def list_markers(db=Depends(get_db)):
    """Return customers as markers where there is a visit scheduled to start today."""
    from datetime import datetime, timedelta

    today = datetime.now().date()
    start = datetime.combine(today, datetime.min.time())
    end = start + timedelta(days=1)

    customers = (
        db.query(Customer)
        .join(VisitSchedule, VisitSchedule.customer_id == Customer.id)
        .filter(VisitSchedule.start_at >= start, VisitSchedule.start_at < end)
        .distinct(Customer.id)
        .all()
    )
    return [
        {"id": c.id, "title": c.name, "lat": c.latitude, "lng": c.longitude, "address": c.address}
        for c in customers
    ]


@app.get("/api/markers/nearby")
def list_markers_nearby(lat: float, lng: float, request: Request, db=Depends(get_db)):
    """Return customers within a square based on user's nearby_distance_km."""
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    distance_km = user.nearby_distance_km or 5.0
    if distance_km <= 0:
        distance_km = 5.0
    delta_lat = distance_km / 111.0
    # avoid div by zero at poles
    denom = 111.0 * max(0.1, abs(math.cos(math.radians(lat))))
    delta_lng = distance_km / denom
    min_lat, max_lat = lat - delta_lat, lat + delta_lat
    min_lng, max_lng = lng - delta_lng, lng + delta_lng

    customers = (
        db.query(Customer)
        .filter(Customer.latitude >= min_lat, Customer.latitude <= max_lat)
        .filter(Customer.longitude >= min_lng, Customer.longitude <= max_lng)
        .all()
    )
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


@app.put("/api/customers/{customer_id}", response_model=CustomerRead)
def update_customer(customer_id: int, payload: CustomerCreate, db=Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    for k, v in payload.dict().items():
        setattr(customer, k, v)
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
    return {
        "id": visit.id,
        "name": visit.name,
        "start_at": visit.start_at.isoformat() if visit.start_at else None,
        "end_at": visit.end_at.isoformat() if visit.end_at else None,
        "result": visit.result,
        "detail": visit.detail,
        "customer_id": visit.customer_id,
    }


@app.put("/api/visits/{visit_id}", response_model=VisitRead)
def update_visit(visit_id: int, payload: VisitCreate, db=Depends(get_db)):
    visit = db.query(VisitSchedule).filter(VisitSchedule.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    visit.name = payload.name
    visit.start_at = _parse_datetime(payload.start_at)
    visit.end_at = _parse_datetime(payload.end_at)
    visit.result = payload.result
    visit.detail = payload.detail
    visit.customer_id = payload.customer_id
    db.commit()
    db.refresh(visit)
    return {
        "id": visit.id,
        "name": visit.name,
        "start_at": visit.start_at.isoformat() if visit.start_at else None,
        "end_at": visit.end_at.isoformat() if visit.end_at else None,
        "result": visit.result,
        "detail": visit.detail,
        "customer_id": visit.customer_id,
    }


@app.delete("/api/visits/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_visit(visit_id: int, db=Depends(get_db)):
    visit = db.query(VisitSchedule).filter(VisitSchedule.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    db.delete(visit)
    db.commit()
    return


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


@app.get("/api/user/settings")
def get_user_settings(request: Request, db=Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return {
        "transport_method": user.transport_method,
        "route_origin": user.route_origin,
        "map_display_type_main": user.map_display_type_main,
        "zoom_setting": user.zoom_setting,
        "nearby_distance_km": user.nearby_distance_km,
        "marker_cluster_max_zoom": user.marker_cluster_max_zoom,
        "toll_usage": user.toll_usage,
    }


@app.put("/api/user/settings")
def update_user_settings(payload: MaptechUserSettings, request: Request, db=Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return {
        "transport_method": user.transport_method,
        "route_origin": user.route_origin,
        "map_display_type_main": user.map_display_type_main,
        "zoom_setting": user.zoom_setting,
        "nearby_distance_km": user.nearby_distance_km,
        "marker_cluster_max_zoom": user.marker_cluster_max_zoom,
        "toll_usage": user.toll_usage,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
