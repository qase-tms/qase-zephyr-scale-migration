from concurrent.futures import ThreadPoolExecutor

from .entities.zephyr_scale import (
    Projects,
    Fields,
    Attachments,
    Suites,
    Cases,
    Runs,
    Milestones,
)
from .service import QaseService, DryRunQaseService, ZephyrScaleService
from .support import ConfigManager, Logger, Mappings, ThrottledThreadPoolExecutor, Pools

_ZEPHYR_SOURCE_POOL_WORKERS = 8


class Importer:
    def __init__(self, config: ConfigManager, logger: Logger, dry_run: bool = False) -> None:
        self.pools = Pools(
            qase_pool=ThrottledThreadPoolExecutor(max_workers=8, requests=250, interval=12),
            source_pool=ThreadPoolExecutor(max_workers=_ZEPHYR_SOURCE_POOL_WORKERS),
        )

        self.logger = logger
        self.config = config
        self.dry_run = dry_run

        self.qase_service = (
            DryRunQaseService(config, logger) if dry_run else QaseService(config, logger)
        )

        self.source_service = ZephyrScaleService(config, logger)

        # users.default accepts a Qase user id or an email address; resolving it
        # up front means an unknown author fails here rather than on every case.
        default_user = self.qase_service.resolve_user_id(self.config.get("users.default"))
        self.mappings = Mappings("zephyr-scale", default_user)

        # Every warn/error becomes a line in the end-of-run migration report
        self.logger.attach_stats(self.mappings.stats)

    def start(self):
        if self.dry_run:
            print("\n\033[33m*** DRY RUN: reading from Zephyr Scale, writing nothing to Qase ***\033[0m\n")
        self.logger.log("Starting Zephyr Scale to Qase migration")

        # Step 1. Import projects and build project map
        self.mappings = Projects(
            self.qase_service,
            self.source_service,
            self.logger,
            self.mappings,
            self.config,
            self.pools,
        ).import_projects()

        if not self.mappings.projects:
            self.logger.log("[Importer] No projects to migrate. Exiting.", "warn")
            self.mappings.stats.print_issues()
            return

        # Step 2. Attachments (no-op: Zephyr Scale attachments are migrated
        #         per entity, inside the Cases and Runs steps)
        self.mappings = Attachments(
            self.qase_service,
            self.source_service,
            self.logger,
            self.mappings,
            self.config,
            self.pools,
        ).import_all_attachments()

        # Step 3. Register Qase system fields (priority / status option ids)
        self.mappings = Fields(
            self.qase_service,
            self.source_service,
            self.logger,
            self.mappings,
            self.config,
            self.pools,
        ).import_fields()

        # Step 4. Import per-project data (suites → cases → runs) in parallel
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(self._import_project_data, project)
                for project in self.mappings.projects
            ]
            for future in futures:
                future.result()

        self.mappings.stats.print()
        self.mappings.stats.print_issues()

        prefix = str(self.config.get("prefix") or "zephyr-scale")
        self.mappings.stats.save(prefix)
        self.mappings.stats.save_xlsx(prefix)
        print(f"\nqase-zephyr-scale-migration v{self.logger.version}")
        if self.logger.log_file:
            print(f"Full log: {self.logger.log_file}")

        if self.dry_run:
            print("\n\033[33m*** DRY RUN complete: nothing was written to Qase ***\033[0m")

    def _import_project_data(self, project: dict):
        self.logger.print_group(f'Importing project: {project["name"]} [{project["code"]}]')

        # Suites (folders)
        self.mappings = Suites(
            self.qase_service,
            self.source_service,
            self.logger,
            self.mappings,
            self.config,
            self.pools,
        ).import_suites(project)

        # Milestones (test plans)
        self.mappings = Milestones(
            self.qase_service,
            self.source_service,
            self.logger,
            self.mappings,
            self.config,
            self.pools,
        ).import_milestones(project)

        # Test cases
        Cases(
            self.qase_service,
            self.source_service,
            self.logger,
            self.mappings,
            self.config,
            self.pools,
        ).import_cases(project)

        # Test runs (cycles + executions)
        self.mappings = Runs(
            self.qase_service,
            self.source_service,
            self.logger,
            self.mappings,
            self.config,
            project,
            self.pools,
        ).import_runs()
