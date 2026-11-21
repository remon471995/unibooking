from storages.backends.s3 import S3Storage

from .safe_names import safe_filename


class SafeS3Storage(S3Storage):
    """نفس S3Storage بس أسماء الملفات بتتحوّل لحروف إنجليزية وأرقام (الاسم العربي بيتشال)."""

    def get_valid_name(self, name):
        return safe_filename(name)
