from ...service.qase import QaseService
from ...service.zephyr_scale import ZephyrScaleService
from ...support.logger import Logger
from ...support.mappings import Mappings
from ...support.pools import Pools


class Attachments:
    """Attachment handling for Zephyr Scale.

    Attachments ARE migrated, just not from here. Zephyr Scale exposes them
    per entity rather than in bulk, so there is nothing useful to do in a
    pre-import phase:

      * test case files come from GET /testcases/{key}/attachments and are
        downloaded and uploaded inside the Cases step, because the hashes have
        to be attached to the case in the same bulk create
      * execution files come from GET /testexecutions/{id}/attachments and are
        handled the same way inside the Runs step

    Both use the Zephyr Bearer token, falling back to Jira Basic auth when the
    file is Jira-hosted rather than Zephyr-hosted.

    Inline images pasted into rich text are the exception and are NOT migrated:
    they are served from CloudFront behind a Forge JWT that only Atlassian's
    Forge runtime issues to the Zephyr app in a browser, which no REST token can
    obtain. Those are replaced with "[Image: filename]" notes and reported.

    This class stays as a no-op so the Importer can call the same steps in the
    same order across every migration script.
    """

    def __init__(
        self,
        qase_service: QaseService,
        source_service: ZephyrScaleService,
        logger: Logger,
        mappings: Mappings,
        config,
        pools: Pools,
    ):
        self.qase = qase_service
        self.zephyr = source_service
        self.logger = logger
        self.mappings = mappings
        self.config = config
        self.pools = pools

    def import_all_attachments(self) -> Mappings:
        self.logger.log(
            "[Attachments] Zephyr Scale exposes attachments per entity, not in bulk; "
            "they are migrated during the Cases and Runs steps."
        )
        return self.mappings
