import logging
import aiohttp
import discord
from redbot.core import checks, commands, Config

log = logging.getLogger("red.pelican")


class PelicanCog(commands.Cog):
    """Pelican Panel server administration"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8472916350, force_registration=True)
        self.config.register_global(pelican_url="", api_token="", app_token="")
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        )
        log.info("PelicanCog loaded")

    async def cog_unload(self):
        await self.session.close()
        log.info("PelicanCog unloaded")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _headers(self, endpoint: str) -> dict:
        """Select client or application token based on endpoint prefix."""
        if endpoint.startswith("/api/application"):
            token = await self.config.app_token()
        else:
            token = await self.config.api_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _get(self, endpoint: str) -> dict:
        base = (await self.config.pelican_url()).rstrip("/")
        url = f"{base}{endpoint}"
        log.debug("GET %s", url)
        async with self.session.get(url, headers=await self._headers(endpoint)) as resp:
            log.debug("GET %s -> %s", url, resp.status)
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, endpoint: str, payload: dict | None = None) -> dict:
        base = (await self.config.pelican_url()).rstrip("/")
        url = f"{base}{endpoint}"
        log.debug("POST %s payload=%s", url, payload)
        async with self.session.post(url, headers=await self._headers(endpoint), json=payload or {}) as resp:
            log.debug("POST %s -> %s", url, resp.status)
            resp.raise_for_status()
            if resp.content_type == "application/json":
                return await resp.json()
            return {}

    async def _put(self, endpoint: str, payload: dict | None = None) -> dict:
        base = (await self.config.pelican_url()).rstrip("/")
        url = f"{base}{endpoint}"
        log.debug("PUT %s payload=%s", url, payload)
        async with self.session.put(url, headers=await self._headers(endpoint), json=payload or {}) as resp:
            log.debug("PUT %s -> %s", url, resp.status)
            resp.raise_for_status()
            if resp.content_type == "application/json":
                return await resp.json()
            return {}

    async def _delete(self, endpoint: str) -> None:
        base = (await self.config.pelican_url()).rstrip("/")
        url = f"{base}{endpoint}"
        log.debug("DELETE %s", url)
        async with self.session.delete(url, headers=await self._headers(endpoint)) as resp:
            log.debug("DELETE %s -> %s", url, resp.status)
            resp.raise_for_status()

    def _api_err(self, exc: Exception) -> str:
        log.error("Pelican API error: %s", exc, exc_info=True)
        if isinstance(exc, aiohttp.ClientResponseError):
            return f"API error {exc.status}: {exc.message}"
        return f"Connection error: {exc}"

    # ------------------------------------------------------------------
    # Setup (bot-owner only)
    # ------------------------------------------------------------------

    @commands.group(name="pelican")
    async def pelican(self, ctx: commands.Context):
        """Pelican Panel administration commands."""

    @pelican.command(name="setup")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_setup(self, ctx: commands.Context, url: str, token: str):
        """Configure the Pelican Panel URL and client API key.

        Example: `[p]pelican setup https://panel.example.com ptlc_xxxx`

        Message is auto-deleted to protect the token.
        """
        await self.config.pelican_url.set(url.rstrip("/"))
        await self.config.api_token.set(token)
        log.info("Pelican client API configured: %s", url.rstrip("/"))
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        await ctx.send("Pelican client API configured.", delete_after=10)

    @pelican.command(name="setupadmin")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_setupadmin(self, ctx: commands.Context, token: str):
        """Set the application (admin) API key.

        Generate this under Admin → API Keys in the panel.
        Example: `[p]pelican setupadmin papp_xxxx`

        Message is auto-deleted to protect the token.
        """
        await self.config.app_token.set(token)
        log.info("Pelican application API key configured")
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        await ctx.send("Pelican application API key configured.", delete_after=10)

    # ------------------------------------------------------------------
    # Server listing & info
    # ------------------------------------------------------------------

    @pelican.command(name="servers")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_servers(self, ctx: commands.Context):
        """List all servers on the panel."""
        try:
            data = await self._get("/api/client")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        servers = data.get("data", [])
        if not servers:
            await ctx.send("No servers found.")
            return

        embed = discord.Embed(title="Pelican Servers", color=discord.Color.blurple())
        for s in servers:
            attr = s.get("attributes", {})
            identifier = attr.get("identifier", "?")
            suspended = attr.get("is_suspended", False)
            installing = attr.get("is_installing", False)
            state = "suspended" if suspended else ("installing" if installing else "active")
            embed.add_field(
                name=f"{attr.get('name', 'Unknown')}  `{identifier}`",
                value=f"Node: {attr.get('node', '?')} | {state}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @pelican.command(name="info")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_info(self, ctx: commands.Context, identifier: str):
        """Show full details for a server."""
        try:
            data = await self._get(f"/api/client/servers/{identifier}")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        attr = data.get("attributes", {})
        limits = attr.get("limits", {})
        embed = discord.Embed(
            title=attr.get("name", identifier),
            description=attr.get("description") or None,
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Identifier", value=f"`{attr.get('identifier')}`", inline=True)
        embed.add_field(name="Node", value=attr.get("node", "?"), inline=True)
        embed.add_field(name="Docker Image", value=attr.get("docker_image", "?"), inline=False)
        embed.add_field(name="RAM Limit", value=f"{limits.get('memory', 0)} MB (0 = unlimited)", inline=True)
        embed.add_field(name="CPU Limit", value=f"{limits.get('cpu', 0)}% (0 = unlimited)", inline=True)
        embed.add_field(name="Disk Limit", value=f"{limits.get('disk', 0)} MB (0 = unlimited)", inline=True)

        sftp = attr.get("sftp_details", {})
        if sftp:
            embed.add_field(
                name="SFTP",
                value=f"`{sftp.get('ip')}:{sftp.get('port')}`",
                inline=False,
            )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Status / resources
    # ------------------------------------------------------------------

    @pelican.command(name="status")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_status(self, ctx: commands.Context, identifier: str):
        """Show live resource usage for a server."""
        try:
            data = await self._get(f"/api/client/servers/{identifier}/resources")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        attr = data.get("attributes", {})
        state = attr.get("current_state", "unknown")
        resources = attr.get("resources", {})

        color = {
            "running": discord.Color.green(),
            "offline": discord.Color.red(),
            "starting": discord.Color.yellow(),
            "stopping": discord.Color.orange(),
        }.get(state, discord.Color.greyple())

        embed = discord.Embed(title=f"Server `{identifier}` — {state}", color=color)
        embed.add_field(name="CPU", value=f"{resources.get('cpu_absolute', 0):.1f}%", inline=True)
        embed.add_field(name="RAM", value=f"{resources.get('memory_bytes', 0) // 1024 // 1024} MB", inline=True)
        embed.add_field(name="Disk", value=f"{resources.get('disk_bytes', 0) // 1024 // 1024} MB", inline=True)
        embed.add_field(name="Net ↑", value=f"{resources.get('network_tx_bytes', 0) // 1024} KB", inline=True)
        embed.add_field(name="Net ↓", value=f"{resources.get('network_rx_bytes', 0) // 1024} KB", inline=True)
        embed.add_field(name="Uptime", value=f"{resources.get('uptime', 0) // 1000}s", inline=True)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Power
    # ------------------------------------------------------------------

    @pelican.command(name="power")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_power(self, ctx: commands.Context, identifier: str, signal: str):
        """Send a power signal to a server.

        Signals: `start` `stop` `restart` `kill`
        """
        valid = ("start", "stop", "restart", "kill")
        if signal not in valid:
            await ctx.send(f"Invalid signal. Choose from: {', '.join(valid)}")
            return
        try:
            await self._post(f"/api/client/servers/{identifier}/power", {"signal": signal})
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Sent `{signal}` to `{identifier}`.")

    @pelican.command(name="restart")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_restart(self, ctx: commands.Context, identifier: str):
        """Restart a server."""
        try:
            await self._post(f"/api/client/servers/{identifier}/power", {"signal": "restart"})
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Restarting `{identifier}`...")

    # ------------------------------------------------------------------
    # Console command
    # ------------------------------------------------------------------

    @pelican.command(name="cmd")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_cmd(self, ctx: commands.Context, identifier: str, *, command: str):
        """Send a console command to a server.

        Example: `[p]pelican cmd 8551552c say Hello world`
        """
        try:
            await self._post(f"/api/client/servers/{identifier}/command", {"command": command})
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Command sent to `{identifier}`.")

    # ------------------------------------------------------------------
    # Activity log
    # ------------------------------------------------------------------

    @pelican.command(name="activity")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_activity(self, ctx: commands.Context, identifier: str):
        """Show recent activity log for a server."""
        try:
            data = await self._get(f"/api/client/servers/{identifier}/activity")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        events = data.get("data", [])[:10]
        if not events:
            await ctx.send("No activity found.")
            return

        embed = discord.Embed(title=f"Activity — `{identifier}`", color=discord.Color.blurple())
        for e in events:
            attr = e.get("attributes", {})
            actor = attr.get("actor", {})
            name = actor.get("username", "system") if actor else "system"
            embed.add_field(
                name=attr.get("event", "?"),
                value=f"By **{name}** — {attr.get('timestamp', '')}",
                inline=False,
            )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    @pelican.command(name="files")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_files(self, ctx: commands.Context, identifier: str, directory: str = "/"):
        """List files in a server directory.

        Example: `[p]pelican files 8551552c /logs`
        """
        try:
            data = await self._get(
                f"/api/client/servers/{identifier}/files/list?directory={directory}"
            )
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        files = data.get("data", [])
        if not files:
            await ctx.send(f"No files found in `{directory}`.")
            return

        lines = []
        for f in files[:30]:
            attr = f.get("attributes", {})
            icon = "📁" if attr.get("is_directory") else "📄"
            size = f"{attr.get('size', 0) // 1024} KB" if not attr.get("is_directory") else ""
            lines.append(f"{icon} `{attr.get('name', '?')}` {size}".strip())

        embed = discord.Embed(
            title=f"Files — `{identifier}:{directory}`",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Backups
    # ------------------------------------------------------------------

    @pelican.group(name="backup")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_backup(self, ctx: commands.Context):
        """Backup management commands."""

    @pelican_backup.command(name="list")
    async def backup_list(self, ctx: commands.Context, identifier: str):
        """List backups for a server."""
        try:
            data = await self._get(f"/api/client/servers/{identifier}/backups")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        backups = data.get("data", [])
        if not backups:
            await ctx.send("No backups found.")
            return

        embed = discord.Embed(title=f"Backups — `{identifier}`", color=discord.Color.blurple())
        for b in backups:
            attr = b.get("attributes", {})
            size = f"{attr.get('bytes', 0) // 1024 // 1024} MB"
            locked = " 🔒" if attr.get("is_locked") else ""
            completed = "✅" if attr.get("completed_at") else "⏳"
            embed.add_field(
                name=f"{completed} {attr.get('name', 'Unnamed')}{locked}",
                value=f"`{attr.get('uuid', '')[:8]}` · {size} · {attr.get('created_at', '')[:10]}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @pelican_backup.command(name="create")
    async def backup_create(self, ctx: commands.Context, identifier: str, *, name: str = ""):
        """Create a new backup for a server.

        Example: `[p]pelican backup create 8551552c pre-update`
        """
        payload = {"name": name} if name else {}
        try:
            data = await self._post(f"/api/client/servers/{identifier}/backups", payload)
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        attr = data.get("attributes", {})
        await ctx.send(
            f"Backup `{attr.get('name', 'Unnamed')}` started (`{attr.get('uuid', '')[:8]}`)."
        )

    @pelican_backup.command(name="delete")
    async def backup_delete(self, ctx: commands.Context, identifier: str, backup_uuid: str):
        """Delete a backup.

        Example: `[p]pelican backup delete 8551552c abc12345`
        """
        try:
            await self._delete(f"/api/client/servers/{identifier}/backups/{backup_uuid}")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Backup `{backup_uuid[:8]}` deleted.")

    @pelican_backup.command(name="restore")
    @checks.admin_or_permissions(administrator=True)
    async def backup_restore(self, ctx: commands.Context, identifier: str, backup_uuid: str):
        """Restore a server from a backup (owner only — this overwrites server files).

        Example: `[p]pelican backup restore 8551552c abc12345`
        """
        try:
            await self._post(
                f"/api/client/servers/{identifier}/backups/{backup_uuid}/restore",
                {"truncate": False},
            )
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Restoring `{identifier}` from backup `{backup_uuid[:8]}`...")

    # ------------------------------------------------------------------
    # Schedules
    # ------------------------------------------------------------------

    @pelican.group(name="schedule")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_schedule(self, ctx: commands.Context):
        """Schedule management commands."""

    @pelican_schedule.command(name="list")
    async def schedule_list(self, ctx: commands.Context, identifier: str):
        """List schedules for a server."""
        try:
            data = await self._get(f"/api/client/servers/{identifier}/schedules")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        schedules = data.get("data", [])
        if not schedules:
            await ctx.send("No schedules found.")
            return

        embed = discord.Embed(title=f"Schedules — `{identifier}`", color=discord.Color.blurple())
        for s in schedules:
            attr = s.get("attributes", {})
            active = "✅" if attr.get("is_active") else "❌"
            cron = (
                f"{attr.get('cron_minute','*')} {attr.get('cron_hour','*')} "
                f"{attr.get('cron_day_of_month','*')} {attr.get('cron_month','*')} "
                f"{attr.get('cron_day_of_week','*')}"
            )
            embed.add_field(
                name=f"{active} {attr.get('name', 'Unnamed')}  (ID: {attr.get('id')})",
                value=f"Cron: `{cron}` | Last run: {attr.get('last_run_at') or 'never'}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @pelican_schedule.command(name="run")
    async def schedule_run(self, ctx: commands.Context, identifier: str, schedule_id: int):
        """Manually trigger a schedule.

        Example: `[p]pelican schedule run 8551552c 3`
        """
        try:
            await self._post(
                f"/api/client/servers/{identifier}/schedules/{schedule_id}/execute"
            )
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Schedule `{schedule_id}` triggered on `{identifier}`.")

    # ------------------------------------------------------------------
    # Subusers
    # ------------------------------------------------------------------

    @pelican.command(name="users")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_users(self, ctx: commands.Context, identifier: str):
        """List subusers for a server."""
        try:
            data = await self._get(f"/api/client/servers/{identifier}/users")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        users = data.get("data", [])
        if not users:
            await ctx.send("No subusers found.")
            return

        embed = discord.Embed(title=f"Subusers — `{identifier}`", color=discord.Color.blurple())
        for u in users:
            attr = u.get("attributes", {})
            perms = len(attr.get("permissions", []))
            embed.add_field(
                name=attr.get("username", "?"),
                value=f"{attr.get('email', '?')} · {perms} permission(s)",
                inline=True,
            )
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Startup variables
    # ------------------------------------------------------------------

    @pelican.command(name="startup")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_startup(self, ctx: commands.Context, identifier: str):
        """List editable startup variables for a server."""
        try:
            data = await self._get(f"/api/client/servers/{identifier}/startup")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        variables = data.get("data", [])
        editable = [v for v in variables if v.get("attributes", {}).get("is_editable")]
        if not editable:
            await ctx.send("No editable startup variables found.")
            return

        embed = discord.Embed(
            title=f"Startup Variables — `{identifier}`", color=discord.Color.blurple()
        )
        for v in editable:
            attr = v.get("attributes", {})
            embed.add_field(
                name=attr.get("name", "?"),
                value=f"Env: `{attr.get('env_variable')}` · Value: `{attr.get('server_value') or attr.get('default_value', '—')}`",
                inline=False,
            )
        await ctx.send(embed=embed)

    @pelican.command(name="setvar")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_setvar(
        self, ctx: commands.Context, identifier: str, env_variable: str, *, value: str
    ):
        """Update a startup variable for a server (owner only).

        Example: `[p]pelican setvar 8551552c PREFIX !`
        """
        try:
            await self._put(
                f"/api/client/servers/{identifier}/startup/variable",
                {"key": env_variable, "value": value},
            )
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Set `{env_variable}` = `{value}` on `{identifier}`.")

    # ------------------------------------------------------------------
    # Server settings
    # ------------------------------------------------------------------

    @pelican.command(name="rename")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_rename(self, ctx: commands.Context, identifier: str, *, new_name: str):
        """Rename a server (owner only)."""
        try:
            await self._post(
                f"/api/client/servers/{identifier}/settings/rename", {"name": new_name}
            )
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Renamed `{identifier}` to **{new_name}**.")

    @pelican.command(name="reinstall")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_reinstall(self, ctx: commands.Context, identifier: str):
        """Reinstall a server (owner only — this will wipe the server)."""
        try:
            await self._post(f"/api/client/servers/{identifier}/settings/reinstall")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Reinstall triggered for `{identifier}`.")

    # ------------------------------------------------------------------
    # Application API — admin-level management (requires papp_ key)
    # ------------------------------------------------------------------

    @pelican.command(name="adminservers")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_adminservers(self, ctx: commands.Context):
        """List all servers on the panel via the application API."""
        try:
            data = await self._get("/api/application/servers")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        servers = data.get("data", [])
        if not servers:
            await ctx.send("No servers found.")
            return

        embed = discord.Embed(title="All Servers (Admin)", color=discord.Color.red())
        for s in servers[:25]:
            attr = s.get("attributes", {})
            suspended = "suspended" if attr.get("suspended") else "active"
            embed.add_field(
                name=f"{attr.get('name', '?')}  `{attr.get('identifier', '?')}`",
                value=f"Node: {attr.get('node', '?')} | {suspended} | ID: {attr.get('id')}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @pelican.command(name="adminusers")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_adminusers(self, ctx: commands.Context):
        """List all panel users via the application API."""
        try:
            data = await self._get("/api/application/users")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        users = data.get("data", [])
        if not users:
            await ctx.send("No users found.")
            return

        embed = discord.Embed(title="All Panel Users (Admin)", color=discord.Color.red())
        for u in users[:25]:
            attr = u.get("attributes", {})
            admin_tag = " 👑" if attr.get("root_admin") else ""
            embed.add_field(
                name=f"{attr.get('username', '?')}{admin_tag}",
                value=f"{attr.get('email', '?')} | ID: {attr.get('id')}",
                inline=True,
            )
        await ctx.send(embed=embed)

    @pelican.command(name="adminnodes")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_adminnodes(self, ctx: commands.Context):
        """List all nodes via the application API."""
        try:
            data = await self._get("/api/application/nodes")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return

        nodes = data.get("data", [])
        if not nodes:
            await ctx.send("No nodes found.")
            return

        embed = discord.Embed(title="Nodes (Admin)", color=discord.Color.red())
        for n in nodes[:25]:
            attr = n.get("attributes", {})
            maintenance = " 🔧 maintenance" if attr.get("maintenance_mode") else ""
            embed.add_field(
                name=f"{attr.get('name', '?')}{maintenance}",
                value=(
                    f"ID: {attr.get('id')} | "
                    f"Memory: {attr.get('memory', 0)} MB | "
                    f"Disk: {attr.get('disk', 0)} MB"
                ),
                inline=False,
            )
        await ctx.send(embed=embed)

    @pelican.command(name="suspend")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_suspend(self, ctx: commands.Context, server_id: int):
        """Suspend a server via the application API (uses numeric ID, not identifier).

        Get the numeric ID from `!pelican adminservers`.
        """
        try:
            await self._post(f"/api/application/servers/{server_id}/suspend")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Server `{server_id}` suspended.")

    @pelican.command(name="unsuspend")
    @checks.admin_or_permissions(administrator=True)
    async def pelican_unsuspend(self, ctx: commands.Context, server_id: int):
        """Unsuspend a server via the application API (uses numeric ID).

        Get the numeric ID from `!pelican adminservers`.
        """
        try:
            await self._post(f"/api/application/servers/{server_id}/unsuspend")
        except Exception as exc:
            await ctx.send(self._api_err(exc))
            return
        await ctx.send(f"Server `{server_id}` unsuspended.")
