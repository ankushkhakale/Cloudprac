"""AWS Boto3 adapter layer with ambient credentials and mock support."""

import os
from typing import Any, Dict, Optional
import boto3
from botocore.exceptions import BotoCoreError, ClientError

from cloudprac.utils.logging import get_logger

ENV_MOCK_AWS = "CLOUDPRAC_MOCK_AWS"
logger = get_logger()


def mask_account_id(account_id: str) -> str:
    """Mask AWS Account ID for privacy in reports and logs (e.g. '1234****9012')."""
    if len(account_id) >= 8:
        return f"{account_id[:4]}****{account_id[-4:]}"
    return "********"


class AWSAdapter:
    """Manages AWS interactions, Boto3 sessions, and environment identification."""

    def __init__(self, region_name: Optional[str] = None, mock_mode: Optional[bool] = None) -> None:
        self._region = region_name or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self._mock_mode = (
            mock_mode if mock_mode is not None
            else os.environ.get(ENV_MOCK_AWS, "0").lower() in ("1", "true", "yes")
        )
        self._session: Optional[boto3.Session] = None

    @property
    def mock_mode(self) -> bool:
        """Whether AWS operations are running in mocked/dry-run mode."""
        return self._mock_mode

    @property
    def region(self) -> str:
        """Current AWS region."""
        return self._region

    def get_session(self) -> boto3.Session:
        """Return Boto3 session utilizing ambient CloudShell credentials."""
        if self._session is None:
            self._session = boto3.Session(region_name=self._region)
        return self._session

    def get_client(self, service_name: str) -> Any:
        """Create a Boto3 service client."""
        return self.get_session().client(service_name)

    def get_caller_identity(self) -> Dict[str, Any]:
        """Fetch caller identity using STS without storing or logging credentials."""
        if self._mock_mode:
            return {
                "UserId": "MOCK_USER_ID_CLOUDPRAC",
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/cloudprac-student",
                "Region": self._region,
                "IsMock": True,
            }

        try:
            sts = self.get_client("sts")
            identity = sts.get_caller_identity()
            return {
                "UserId": identity.get("UserId", "unknown"),
                "Account": identity.get("Account", "unknown"),
                "Arn": identity.get("Arn", "unknown"),
                "Region": self._region,
                "IsMock": False,
            }
        except (BotoCoreError, ClientError) as e:
            logger.debug(f"Failed to obtain STS caller identity: {e}")
            return {
                "UserId": "unavailable",
                "Account": "unavailable",
                "Arn": "unavailable",
                "Region": self._region,
                "Error": str(e),
                "IsMock": False,
            }
