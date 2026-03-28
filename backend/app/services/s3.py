import logging
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings

logger = logging.getLogger(__name__)

# Local dev upload directory (relative to where the server runs)
_LOCAL_UPLOAD_DIR = Path("uploads")


def _s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )


def _is_s3_configured() -> bool:
    return bool(get_settings().s3_bucket)


def generate_presigned_upload_url(key: str, content_type: str = "video/mp4") -> str:
    """
    Returns a presigned PUT URL for direct browser→S3 upload (expires in 10 min).
    Falls back to a local file:// path when S3_BUCKET is not configured.
    """
    if not _is_s3_configured():
        dest = _LOCAL_UPLOAD_DIR / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        logger.info("S3 not configured — local dev upload path: %s", dest)
        return dest.resolve().as_uri()

    settings = get_settings()
    try:
        url = _s3_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.s3_bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=600,  # 10 minutes
        )
        logger.info("Presigned upload URL generated for key: %s", key)
        return url
    except ClientError as exc:
        logger.error("Failed to generate presigned upload URL for %s: %s", key, exc)
        raise


def download_video(s3_key: str, local_path: str) -> None:
    """
    Download a video from S3 (or local uploads dir) to local_path.

    In local dev (no S3_BUCKET set), copies the file from the uploads/ directory.
    In production, uses boto3 download_file.
    """
    import shutil

    if not _is_s3_configured():
        src = _LOCAL_UPLOAD_DIR / s3_key
        shutil.copy2(src, local_path)
        logger.info("Local dev — copied %s → %s", src, local_path)
        return

    settings = get_settings()
    _s3_client().download_file(settings.s3_bucket, s3_key, local_path)
    logger.info("Downloaded s3://%s/%s → %s", settings.s3_bucket, s3_key, local_path)


def upload_file(local_path: str, key: str, content_type: str = "application/octet-stream") -> None:
    """
    Upload a local file to S3 (or copy to local uploads dir in dev).
    """
    import shutil

    if not _is_s3_configured():
        dest = _LOCAL_UPLOAD_DIR / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dest)
        logger.info("Local dev — copied %s → %s", local_path, dest)
        return

    settings = get_settings()
    _s3_client().upload_file(
        local_path, settings.s3_bucket, key, ExtraArgs={"ContentType": content_type}
    )
    logger.info("Uploaded %s → s3://%s/%s", local_path, settings.s3_bucket, key)


def delete_object(key: str) -> None:
    """
    Delete an object from S3 (or local uploads dir in dev). No-op if the key
    does not exist.
    """
    if not _is_s3_configured():
        dest = _LOCAL_UPLOAD_DIR / key
        if dest.exists():
            dest.unlink()
            logger.info("Local dev — deleted %s", dest)
        return

    settings = get_settings()
    try:
        _s3_client().delete_object(Bucket=settings.s3_bucket, Key=key)
        logger.info("Deleted s3://%s/%s", settings.s3_bucket, key)
    except ClientError as exc:
        logger.warning("Failed to delete S3 object %s: %s", key, exc)


def generate_presigned_download_url(key: str) -> str:
    """
    Returns a presigned GET URL for video/file access (expires in 1 hour).
    Falls back to an HTTP path served by the local StaticFiles mount when
    S3_BUCKET is not configured.
    """
    if not _is_s3_configured():
        logger.info("S3 not configured — using local dev HTTP path for key: %s", key)
        return f"/uploads/{key}"

    settings = get_settings()
    try:
        url = _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=3600,  # 1 hour
        )
        return url
    except ClientError as exc:
        logger.error("Failed to generate presigned download URL for %s: %s", key, exc)
        raise


def generate_presigned_urls(keys: list[str]) -> list[str]:
    """
    Batch presigned URL generation. Returns one URL per key, in the same order.
    Uses generate_presigned_download_url for each key.
    """
    return [generate_presigned_download_url(key) for key in keys]
