from ..api.zephyr_scale import ZephyrScaleApiClient
from ..support.config_manager import ConfigManager
from ..support.logger import Logger

# Page size is not configuration. Zephyr Scale caps maxResults at 100 on the
# endpoints this script reads, and a customer has no basis on which to choose a
# different number.
_PAGE_SIZE = 100


class ZephyrScaleService:
    """Thin service wrapper around ZephyrScaleApiClient.

    Entity classes call this instead of the API client directly so retry /
    business-logic concerns stay in one place.
    """

    def __init__(self, config: ConfigManager, logger: Logger):
        self.config = config
        self.logger = logger

        token = config.get("zephyr.api_token") or ""
        host = config.get("zephyr.base_url") or "https://api.zephyrscale.smartbear.com/v2"

        self.client = ZephyrScaleApiClient(
            token=token,
            logger=logger,
            base_url=host,
            page_size=_PAGE_SIZE,
        )

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def get_projects(self) -> list:
        self.logger.log("[ZephyrScale] Fetching projects")
        return self.client.get_projects()

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    def get_folders(self, project_key: str, folder_type: str = "TEST_CASE") -> list:
        self.logger.log(f"[ZephyrScale] Fetching {folder_type} folders for {project_key}")
        return self.client.get_folders(project_key, folder_type)

    # ------------------------------------------------------------------
    # Test cases
    # ------------------------------------------------------------------

    def get_test_cases(self, project_key: str, folder_id: int = None):
        """Yield pages of test cases."""
        yield from self.client.get_test_cases(project_key, folder_id)

    def get_test_case(self, test_case_key: str) -> dict:
        return self.client.get_test_case(test_case_key)

    def get_test_steps(self, test_case_key: str) -> list:
        return self.client.get_test_steps(test_case_key)

    # ------------------------------------------------------------------
    # Test cycles
    # ------------------------------------------------------------------

    def get_test_cycles(self, project_key: str, created_after: int = 0):
        """Yield pages of test cycles."""
        yield from self.client.get_test_cycles(project_key, created_after)

    def get_test_cycle(self, cycle_key: str) -> dict:
        return self.client.get_test_cycle(cycle_key)

    def get_test_plans(self, project_key: str):
        """Yield pages of test plans."""
        yield from self.client.get_test_plans(project_key)

    # ------------------------------------------------------------------
    # Test executions
    # ------------------------------------------------------------------

    def get_test_executions(self, project_key: str, test_cycle_key: str = None):
        """Yield pages of test executions."""
        yield from self.client.get_test_executions(project_key, test_cycle_key)

    # ------------------------------------------------------------------
    # Statuses and priorities
    # ------------------------------------------------------------------

    def get_priorities(self, project_key: str) -> list:
        return self.client.get_priorities(project_key)

    def get_statuses(self, project_key: str, status_type: str = "TEST_CASE") -> list:
        return self.client.get_statuses(project_key, status_type)

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    def get_test_case_attachments(self, tc_key: str) -> list:
        return self.client.get_test_case_attachments(tc_key)

    def get_test_execution_attachments(self, ex_id) -> list:
        return self.client.get_test_execution_attachments(ex_id)

    def download_attachment_bytes(
        self,
        url: str,
        jira_email: str = None,
        jira_api_token: str = None,
    ) -> bytes:
        return self.client.download_attachment_bytes(url, jira_email, jira_api_token)

    # ------------------------------------------------------------------
    # Custom fields
    # ------------------------------------------------------------------

    def get_custom_fields(self, project_key: str) -> list:
        return self.client.get_custom_fields(project_key)
