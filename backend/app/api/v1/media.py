"""照片分步上传（计划 0016 阶段 B）：采集端先逐张查重、上传照片，再提交只含 URL 的巡检包。

整趟照片不必再以 base64 塞进一个包里，车端内存占用与点数无关。照片按内容 SHA-256 寻址（D6），
扩展名按文件魔数定，与巡检包 base64 照片同一规则，所以同一份字节无论走哪条路都是同一个 URL。
上传了但没被任何采样点引用的照片暂不清理（技术债台账）。
"""
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.schemas import patrol as patrol_schema
from app.schemas.media import SHA256_PATTERN, MediaExistsOut, MediaUploadOut
from app.services.storage import Storage, get_storage, photo_suffix

router = APIRouter(prefix="/media", tags=["media"])

UPLOAD_TYPES = ("image/jpeg", "image/png")


def _too_large() -> HTTPException:
    limit = patrol_schema.MAX_PHOTO_BYTES // (1024 * 1024)
    return HTTPException(status_code=413, detail=f"照片超过大小上限 {limit}MB")


@router.post(
    "", response_model=MediaUploadOut, status_code=201,
    responses={200: {"description": "同一张照片已存在，未重写", "model": MediaUploadOut}},
    openapi_extra={"requestBody": {"required": True, "content": {
        media_type: {"schema": {"type": "string", "format": "binary"}} for media_type in UPLOAD_TYPES
    }}},
)
async def upload_media(request: Request, response: Response, storage: Storage = Depends(get_storage)):
    """上传一张照片（请求体是原始图片字节，≤8MB）。新建返回 201，已存在返回 200，URL 相同。"""
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type not in UPLOAD_TYPES:
        raise HTTPException(status_code=415, detail="照片须以原始字节上传，Content-Type 为 image/jpeg 或 image/png")
    limit = patrol_schema.MAX_PHOTO_BYTES
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise _too_large()
    if not body:
        raise HTTPException(status_code=422, detail="照片为空")
    data = bytes(body)
    url, created = await run_in_threadpool(storage.save_tracked, data, photo_suffix(data))
    if not created:
        response.status_code = 200
    return MediaUploadOut(url=url, sha256=hashlib.sha256(data).hexdigest(), created=created)


@router.get("/exists", response_model=MediaExistsOut)
def media_exists(
    sha256: str = Query(pattern=SHA256_PATTERN, description="照片内容的 SHA-256（十六进制，大小写均可）"),
    storage: Storage = Depends(get_storage),
):
    """按内容 SHA-256 查照片是否已在平台上；在则返回 URL，采集端据此跳过上传。"""
    url = storage.find(sha256.lower())
    return MediaExistsOut(exists=url is not None, url=url)
