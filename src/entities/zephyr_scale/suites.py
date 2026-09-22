import asyncio

from ...service.qase import QaseService
from ...service.zephyr_scale import ZephyrScaleService
from ...support.config_manager import ConfigManager
from ...support.logger import Logger
from ...support.mappings import Mappings
from ...support.pools import Pools


class Suites:
    """Import Zephyr Scale folders → Qase suites.

    Zephyr Scale folders form a tree via ``parentId``. We do a single pass:
    build a parent-child index, then recursively create suites from roots down
    so every parent exists before its children.
    """

    def __init__(
        self,
        qase_service: QaseService,
        source_service: ZephyrScaleService,
        logger: Logger,
        mappings: Mappings,
        config: ConfigManager,
        pools: Pools,
    ):
        self.qase = qase_service
        self.zephyr = source_service
        self.config = config
        self.logger = logger
        self.mappings = mappings
        self.pools = pools

    def import_suites(self, project: dict) -> Mappings:
        return asyncio.run(self._import_suites_async(project))

    async def _import_suites_async(self, project: dict) -> Mappings:
        code = project["code"]
        zephyr_key = project["zephyr_key"]

        self.logger.log(f"[{code}][Suites] Fetching folders from Zephyr Scale")
        folders = await self.pools.source(
            self.zephyr.get_folders, zephyr_key, "TEST_CASE"
        )

        if not folders:
            self.logger.log(f"[{code}][Suites] No folders found")
            return self.mappings

        self.logger.log(f"[{code}][Suites] Found {len(folders)} folder(s)")
        self.mappings.stats.add_entity_count(code, "suites", "zephyr-scale", len(folders))

        if code not in self.mappings.suites:
            self.mappings.suites[code] = {}

        # Build parent→children index
        by_id = {f["id"]: f for f in folders}
        children_of = {}
        roots = []
        for f in folders:
            pid = f.get("parentId")
            if pid and pid in by_id:
                children_of.setdefault(pid, []).append(f)
            else:
                roots.append(f)

        created = 0
        async def create_folder(folder: dict, parent_qase_id=None):
            nonlocal created
            title = (folder.get("name") or "").strip() or f"Folder {folder['id']}"
            try:
                qase_id = await self.pools.qs(
                    self.qase.create_suite, code, title, "", parent_qase_id
                )
                self.mappings.suites[code][folder["id"]] = qase_id
                created += 1
                self.logger.log(f"[{code}][Suites] Created suite: {title} (id={qase_id})")
            except Exception as e:
                self.logger.log(
                    f"[{code}][Suites] Failed to create suite {title!r}: {e}", "error"
                )
                return

            for child in children_of.get(folder["id"], []):
                await create_folder(child, qase_id)

        await asyncio.gather(*[create_folder(root) for root in roots])

        self.mappings.stats.add_entity_count(code, "suites", "qase", created)
        self.logger.log(f"[{code}][Suites] Created {created}/{len(folders)} suite(s)")
        return self.mappings
