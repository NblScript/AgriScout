"""照片分步上传 DTO（计划 0016 阶段 B）：rover 先逐张查重、上传照片，再提交只含 URL 的巡检包。"""
from pydantic import BaseModel, Field

SHA256_PATTERN = r"^[0-9a-fA-F]{64}$"


class MediaUploadOut(BaseModel):
    url: str = Field(description="照片 URL（/media/<sha256>.<扩展名>），巡检包的 photo 直接填它")
    sha256: str = Field(description="照片内容的 SHA-256（小写十六进制）")
    created: bool = Field(description="本次是否新建了文件；同一张照片已存在时为 false")


class MediaExistsOut(BaseModel):
    exists: bool
    url: str | None = None
