#!/usr/bin/env node
/**
 * Publish a product notice on production (Banner + IM 官方号).
 *
 *   pnpm publish:notice -- --title "…" --body "…" [--severity high] [--surface both|modal]
 *
 * Uses DEPLOY_SSH_* from deploy/.env.deploy.local. Runs create+publish inside
 * the live api container (no admin password needed). Template copy →
 * docs/05-平台与运维/产品公告文案模板.md
 * Surfaces ``inbox`` / ``both`` / ``modal`` also write IM 官方号 on first publish.
 */
import { loadDeployEnv, sshScript } from "./load-deploy-env.mjs";

loadDeployEnv();

function arg(name, fallback = "") {
  const i = process.argv.indexOf(`--${name}`);
  if (i === -1 || i + 1 >= process.argv.length) return fallback;
  return process.argv[i + 1];
}

const title = arg("title").trim();
const body = arg("body").trim();
const severity = arg("severity", "high").trim() || "high";
const surface = arg("surface", "both").trim() || "both";
const dismiss = arg("dismiss", "once").trim() || "once";

if (!title || !body) {
  console.error(
    'usage: pnpm publish:notice -- --title "系统更新 · 约 12:30" --body "…" [--severity high] [--surface both]',
  );
  process.exit(1);
}

// Escape for embedding in a single-quoted remote Python string via JSON.
const payload = JSON.stringify({ title, body, severity, surface, dismiss });

const deployDir = process.env.AGENTCORE_DEPLOY_DIR?.trim() || "";
const deployDirExport = deployDir
  ? `export AGENTCORE_DEPLOY_DIR=${JSON.stringify(deployDir)}\n`
  : "";

const remote = `set -euo pipefail
${deployDirExport}HOME_DIR="\${AGENTCORE_HOME:-/opt/agentcore}"
DEPLOY_DIR="\${AGENTCORE_DEPLOY_DIR:-\$HOME_DIR/repo/deploy}"
cd "\$DEPLOY_DIR"
echo "==> publish product notice via agentcore-api"
docker exec -i agentcore-api python - <<'PY'
import asyncio, json
from datetime import UTC, datetime, timedelta
from sqlalchemy import select

from agentcore.db.base import async_session_factory
from agentcore.db.models import User
from agentcore.db.repositories import (
    ChatRepository,
    ProductNoticeRepository,
    SharedSpaceRepository,
    UserBlockRepository,
    UserDirectoryRepository,
    UserRepository,
)
from agentcore.messaging import MessagingService
from agentcore.messaging.hub import HubChatEventPublisher, default_chat_hub

SPEC = json.loads(${JSON.stringify(payload)})

async def main() -> None:
    async with async_session_factory() as session:
        admin = (
            await session.execute(
                select(User).where(User.role == "admin", User.deleted_at.is_(None)).limit(1)
            )
        ).scalar_one_or_none()
        if admin is None:
            raise SystemExit("no admin user for created_by")
        repo = ProductNoticeRepository(session)
        row = await repo.create(
            title=SPEC["title"],
            body=SPEC["body"],
            severity=SPEC["severity"],
            surface=SPEC["surface"],
            dismiss_policy=SPEC["dismiss"],
            created_by=str(admin.user_id),
            end_at=datetime.now(UTC) + timedelta(hours=2),
        )
        first = row.status != "published"
        published = await repo.publish(row.id)
        if published is None:
            raise SystemExit("publish failed")
        if first and published.surface in ("inbox", "both", "modal"):
            messaging = MessagingService(
                users=UserRepository(session),
                chats=ChatRepository(session),
                blocks=UserBlockRepository(session),
                directory=UserDirectoryRepository(session),
                events=HubChatEventPublisher(default_chat_hub()),
                shared_spaces=SharedSpaceRepository(session),
            )
            await messaging.publish_product_notice(
                notice_id=published.id,
                title=published.title,
                body=published.body,
                severity=published.severity,
                surface=published.surface,
                cta_label=published.cta_label,
                cta_url=published.cta_url,
            )
        print(json.dumps({"id": published.id, "status": published.status, "title": published.title}))

asyncio.run(main())
PY
`;

sshScript(remote);
console.log("notice published");
