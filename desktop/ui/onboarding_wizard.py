"""Multi-step Application Onboarding & Connection Wizard for SentinelOps Control Center."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.api.client import SentinelOpsClient
from desktop.api.models import ConnectorCreateDTO, ProjectDTO, ProjectReadinessDTO
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals
from desktop.workers.task_runner import TaskRunner


def _format_relative_time(dt: Optional[datetime]) -> str:
    """Format datetime as human-readable relative time string."""
    if dt is None:
        return "No telemetry received"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = (now - dt).total_seconds()
    if diff < 0:
        diff = 0
    if diff < 60:
        return "Just now"
    minutes = int(diff / 60)
    if minutes < 60:
        return f"{minutes} min{'s' if minutes != 1 else ''} ago"
    hours = int(minutes / 60)
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(hours / 24)
    return f"{days} day{'s' if days != 1 else ''} ago"


class OnboardingWizardDialog(QDialog):
    """End-to-End Onboarding & Connection Dialog."""

    def __init__(self, client: SentinelOpsClient, task_runner: TaskRunner, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.task_runner = task_runner
        self.state = AppState()

        self.created_project: Optional[ProjectDTO] = None
        self.poller_connector: Optional[Dict[str, Any]] = None
        self.webhook_connector: Optional[ConnectorCreateDTO] = None
        self.readiness_status: Optional[ProjectReadinessDTO] = None

        self.setWindowTitle("Onboard Application — SentinelOps")
        self.setMinimumSize(680, 560)
        self.setModal(True)

        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        # Header Title & Step Indicator
        self.title_label = QLabel("Onboard New Application", self)
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #F8FAFC;")
        main_layout.addWidget(self.title_label)

        self.step_label = QLabel("Step 1 of 4: Project Source", self)
        self.step_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #38BDF8;")
        main_layout.addWidget(self.step_label)

        # Content Stack
        self.stack = QStackedWidget(self)
        self._init_step1_source()
        self._init_step2_health()
        self._init_step3_telemetry()
        self._init_step4_readiness()
        main_layout.addWidget(self.stack, 1)

        # Global Error / Status Banner
        self.status_banner = QLabel("", self)
        self.status_banner.setWordWrap(True)
        self.status_banner.setStyleSheet(
            "padding: 8px 12px; border-radius: 6px; background-color: #7F1D1D; color: #FEE2E2; font-size: 12px;"
        )
        self.status_banner.hide()
        main_layout.addWidget(self.status_banner)

        # Busy Progress Bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        main_layout.addWidget(self.progress_bar)

    def _show_error(self, message: str) -> None:
        self.status_banner.setText(f"✕ {message}")
        self.status_banner.setStyleSheet(
            "padding: 8px 12px; border-radius: 6px; background-color: #7F1D1D; color: #FEE2E2; font-size: 12px;"
        )
        self.status_banner.show()

    def _show_info(self, message: str) -> None:
        self.status_banner.setText(f"✓ {message}")
        self.status_banner.setStyleSheet(
            "padding: 8px 12px; border-radius: 6px; background-color: #064E3B; color: #D1FAE5; font-size: 12px;"
        )
        self.status_banner.show()

    def _clear_status(self) -> None:
        self.status_banner.hide()
        self.status_banner.setText("")

    # -------------------------------------------------------------------------
    # STEP 1: Source Selection
    # -------------------------------------------------------------------------
    def _init_step1_source(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        desc = QLabel(
            "Enter your project name and connect source code. SentinelOps will index the repository "
            "to construct knowledge base context for automated investigations.",
            page,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94A3B8; font-size: 13px;")
        layout.addWidget(desc)

        form = QFormLayout()
        form.setSpacing(12)

        self.name_edit = QLineEdit(page)
        self.name_edit.setPlaceholderText("e.g. Order Service")
        form.addRow("Application Name *:", self.name_edit)

        self.desc_edit = QLineEdit(page)
        self.desc_edit.setPlaceholderText("Optional description")
        form.addRow("Description:", self.desc_edit)

        layout.addLayout(form)

        # Source Radio Group
        source_group = QGroupBox("Source Location", page)
        source_layout = QVBoxLayout(source_group)
        source_layout.setSpacing(10)

        self.github_radio = QRadioButton("Public GitHub Repository (recommended)", source_group)
        self.github_radio.setChecked(True)
        self.local_radio = QRadioButton("Local Repository Directory", source_group)
        source_layout.addWidget(self.github_radio)
        source_layout.addWidget(self.local_radio)

        # GitHub fields container
        self.github_container = QWidget(source_group)
        gh_form = QFormLayout(self.github_container)
        gh_form.setContentsMargins(20, 0, 0, 0)
        gh_form.setSpacing(8)

        self.repo_url_edit = QLineEdit(self.github_container)
        self.repo_url_edit.setPlaceholderText("https://github.com/owner/repository")
        gh_form.addRow("GitHub HTTPS URL *:", self.repo_url_edit)

        self.branch_edit = QLineEdit(self.github_container)
        self.branch_edit.setPlaceholderText("main (default)")
        gh_form.addRow("Branch (optional):", self.branch_edit)
        source_layout.addWidget(self.github_container)

        # Local directory container
        self.local_container = QWidget(source_group)
        local_h = QHBoxLayout(self.local_container)
        local_h.setContentsMargins(20, 0, 0, 0)
        local_h.setSpacing(8)

        self.local_path_edit = QLineEdit(self.local_container)
        self.local_path_edit.setPlaceholderText("C:/path/to/project/workspace")
        local_h.addWidget(self.local_path_edit, 1)

        browse_btn = QPushButton("Browse...", self.local_container)
        browse_btn.clicked.connect(self._on_browse_local_folder)
        local_h.addWidget(browse_btn)

        source_layout.addWidget(self.local_container)
        self.local_container.hide()

        self.github_radio.toggled.connect(self._on_source_type_toggled)
        layout.addWidget(source_group)
        layout.addStretch()

        # Navigation
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel", page)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        self.step1_next_btn = QPushButton("Next: Connect Source ➔", page)
        self.step1_next_btn.setStyleSheet(
            "background-color: #2563EB; color: #FFFFFF; font-weight: 600; padding: 6px 16px; border-radius: 6px;"
        )
        self.step1_next_btn.clicked.connect(self._on_step1_next)
        btn_box.addWidget(self.step1_next_btn)

        layout.addLayout(btn_box)
        self.stack.addWidget(page)

    def _on_source_type_toggled(self, checked: bool) -> None:
        if self.github_radio.isChecked():
            self.github_container.show()
            self.local_container.hide()
        else:
            self.github_container.hide()
            self.local_container.show()

    def _on_browse_local_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Project Workspace Directory")
        if folder:
            self.local_path_edit.setText(folder)

    def _on_step1_next(self) -> None:
        self._clear_status()
        name = self.name_edit.text().strip()
        if not name:
            self._show_error("Application Name is required.")
            return

        is_github = self.github_radio.isChecked()
        if is_github:
            url = self.repo_url_edit.text().strip()
            if not url:
                self._show_error("GitHub repository URL is required.")
                return
            branch = self.branch_edit.text().strip() or None
            self._execute_step1_github(name, url, branch, self.desc_edit.text().strip() or None)
        else:
            path = self.local_path_edit.text().strip()
            if not path:
                self._show_error("Local workspace directory path is required.")
                return
            self._execute_step1_local(name, path, self.desc_edit.text().strip() or None)

    def _execute_step1_github(self, name: str, repo_url: str, branch: Optional[str], description: Optional[str]) -> None:
        self.progress_bar.show()
        self.step1_next_btn.setEnabled(False)

        def _worker():
            return self.client.register_github_project(
                name=name,
                repo_url=repo_url,
                branch=branch,
                description=description,
            )

        def _on_success(project: ProjectDTO):
            self.progress_bar.hide()
            self.step1_next_btn.setEnabled(True)
            self.created_project = project
            self._show_info(f"Source connected & indexed! Project ID: {project.project_id}")
            self._advance_to_step(1)

        def _on_error(exc: Exception):
            self.progress_bar.hide()
            self.step1_next_btn.setEnabled(True)
            self._show_error(f"Failed to onboard GitHub repository: {exc}")

        self.task_runner.run(_worker, on_success=_on_success, on_error=_on_error)

    def _execute_step1_local(self, name: str, workspace_path: str, description: Optional[str]) -> None:
        self.progress_bar.show()
        self.step1_next_btn.setEnabled(False)

        def _worker():
            return self.client.register_project(
                name=name,
                workspace_path=workspace_path,
                description=description,
            )

        def _on_success(project: ProjectDTO):
            self.progress_bar.hide()
            self.step1_next_btn.setEnabled(True)
            self.created_project = project
            self._show_info(f"Local workspace indexed! Project ID: {project.project_id}")
            self._advance_to_step(1)

        def _on_error(exc: Exception):
            self.progress_bar.hide()
            self.step1_next_btn.setEnabled(True)
            self._show_error(f"Failed to onboard local workspace: {exc}")

        self.task_runner.run(_worker, on_success=_on_success, on_error=_on_error)

    # -------------------------------------------------------------------------
    # STEP 2: Deployment & Health Polling
    # -------------------------------------------------------------------------
    def _init_step2_health(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        desc = QLabel(
            "Configure outbound health monitoring. SentinelOps will periodically probe your deployed "
            "endpoint to verify availability and detect service disruptions.",
            page,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94A3B8; font-size: 13px;")
        layout.addWidget(desc)

        form = QFormLayout()
        form.setSpacing(12)

        self.preset_combo = QComboBox(page)
        self.preset_combo.addItems(["Generic HTTP", "Railway", "Render", "Vercel"])
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        form.addRow("Platform Preset:", self.preset_combo)

        self.target_url_edit = QLineEdit(page)
        self.target_url_edit.setPlaceholderText("https://example.com/health")
        form.addRow("Health Target URL *:", self.target_url_edit)

        self.poll_interval_edit = QLineEdit("60", page)
        self.poll_interval_edit.setPlaceholderText("60")
        form.addRow("Poll Interval (sec):", self.poll_interval_edit)

        layout.addLayout(form)

        # Health Test Button & Result Box
        h_test_box = QHBoxLayout()
        self.test_health_btn = QPushButton("Test Health Endpoint", page)
        self.test_health_btn.clicked.connect(self._on_test_health)
        h_test_box.addWidget(self.test_health_btn)
        h_test_box.addStretch()
        layout.addLayout(h_test_box)

        self.health_result_lbl = QLabel("", page)
        self.health_result_lbl.setStyleSheet("font-size: 12px; color: #94A3B8;")
        layout.addWidget(self.health_result_lbl)

        layout.addStretch()

        # Navigation
        btn_box = QHBoxLayout()
        back_btn = QPushButton("⏴ Back", page)
        back_btn.clicked.connect(lambda: self._advance_to_step(0))
        btn_box.addWidget(back_btn)

        btn_box.addStretch()

        skip_btn = QPushButton("Skip Health Polling", page)
        skip_btn.clicked.connect(lambda: self._advance_to_step(2))
        btn_box.addWidget(skip_btn)

        self.step2_next_btn = QPushButton("Next: Telemetry Setup ➔", page)
        self.step2_next_btn.setStyleSheet(
            "background-color: #2563EB; color: #FFFFFF; font-weight: 600; padding: 6px 16px; border-radius: 6px;"
        )
        self.step2_next_btn.clicked.connect(self._on_step2_next)
        btn_box.addWidget(self.step2_next_btn)

        layout.addLayout(btn_box)
        self.stack.addWidget(page)

    def _on_preset_changed(self, text: str) -> None:
        if text == "Railway":
            self.target_url_edit.setPlaceholderText("https://your-service.up.railway.app/health")
        elif text == "Render":
            self.target_url_edit.setPlaceholderText("https://your-service.onrender.com/health")
        elif text == "Vercel":
            self.target_url_edit.setPlaceholderText("https://your-service.vercel.app/api/health")
        else:
            self.target_url_edit.setPlaceholderText("https://example.com/health")

    def _on_test_health(self) -> None:
        url = self.target_url_edit.text().strip()
        if not url:
            self._show_error("Please enter a Health Target URL to test.")
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            self._show_error("Target URL must start with http:// or https://")
            return

        self._clear_status()
        self.progress_bar.show()
        self.test_health_btn.setEnabled(False)

        def _worker():
            # Create poller connector on the fly if project exists
            project_id = self.created_project.project_id if self.created_project else "temp"
            payload = {
                "project_id": project_id,
                "name": f"{self.created_project.name if self.created_project else 'Health'} Poller",
                "connector_type": "http_poller",
                "config": {
                    "url": url,
                    "poll_interval_seconds": int(self.poll_interval_edit.text().strip() or "60"),
                },
            }
            conn = self.client.create_connector(payload)
            test_res = self.client.test_connector(conn.connector_id)
            return conn, test_res

        def _on_success(res):
            conn, test_res = res
            self.progress_bar.hide()
            self.test_health_btn.setEnabled(True)
            self.poller_connector = {"id": conn.connector_id, "url": url}
            status_code = test_res.get("status_code", 200)
            self.health_result_lbl.setText(f"✓ Health probe succeeded: HTTP {status_code}")
            self.health_result_lbl.setStyleSheet("font-size: 12px; color: #34D399; font-weight: 600;")
            self._show_info("Health poller verified and registered!")

        def _on_error(exc: Exception):
            self.progress_bar.hide()
            self.test_health_btn.setEnabled(True)
            self.health_result_lbl.setText(f"✕ Connectivity test failed: {exc}")
            self.health_result_lbl.setStyleSheet("font-size: 12px; color: #F87171;")
            self._show_error(f"Health check failed: {exc}")

        self.task_runner.run(_worker, on_success=_on_success, on_error=_on_error)

    def _on_step2_next(self) -> None:
        url = self.target_url_edit.text().strip()
        if url and not self.poller_connector:
            # User entered URL but hasn't created connector yet; do it now
            self._on_test_health()
            return
        self._advance_to_step(2)

    # -------------------------------------------------------------------------
    # STEP 3: Telemetry (Webhook Intake)
    # -------------------------------------------------------------------------
    def _init_step3_telemetry(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        desc = QLabel(
            "Configure inbound webhook telemetry. Your deployed service can push logs, exceptions, "
            "and runtime signals directly to SentinelOps.",
            page,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94A3B8; font-size: 13px;")
        layout.addWidget(desc)

        self.enable_webhook_cb = QCheckBox("Enable Inbound Webhook Telemetry", page)
        self.enable_webhook_cb.setChecked(True)
        self.enable_webhook_cb.toggled.connect(self._on_webhook_cb_toggled)
        layout.addWidget(self.enable_webhook_cb)

        self.webhook_box = QGroupBox("Webhook Ingress Configuration", page)
        wb_layout = QVBoxLayout(self.webhook_box)
        wb_layout.setSpacing(10)

        # Ingress Warning Banner (displayed if public ingress missing)
        self.ingress_warn_banner = QLabel(
            "⚠️ External Ingress Warning: SentinelOps is running locally without a PUBLIC_INGRESS_URL. "
            "Cloud-hosted targets (Railway/Render/Vercel) cannot post webhooks to localhost without a "
            "public tunnel or reverse proxy.",
            self.webhook_box,
        )
        self.ingress_warn_banner.setWordWrap(True)
        self.ingress_warn_banner.setStyleSheet(
            "padding: 8px 12px; border-radius: 6px; background-color: #78350F; color: #FDE68A; font-size: 12px;"
        )
        wb_layout.addWidget(self.ingress_warn_banner)

        # Endpoint URL
        wb_layout.addWidget(QLabel("Ingestion URL:", self.webhook_box))
        url_h = QHBoxLayout()
        self.webhook_url_edit = QLineEdit(self.webhook_box)
        self.webhook_url_edit.setReadOnly(True)
        url_h.addWidget(self.webhook_url_edit, 1)

        self.copy_url_btn = QPushButton("Copy", self.webhook_box)
        self.copy_url_btn.clicked.connect(lambda: self._copy_to_clipboard(self.webhook_url_edit.text()))
        url_h.addWidget(self.copy_url_btn)
        wb_layout.addLayout(url_h)

        # One-time Secret
        wb_layout.addWidget(QLabel("Generated Auth Secret (One-Time Display):", self.webhook_box))
        sec_h = QHBoxLayout()
        self.webhook_sec_edit = QLineEdit(self.webhook_box)
        self.webhook_sec_edit.setReadOnly(True)
        sec_h.addWidget(self.webhook_sec_edit, 1)

        self.copy_sec_btn = QPushButton("Copy", self.webhook_box)
        self.copy_sec_btn.clicked.connect(lambda: self._copy_to_clipboard(self.webhook_sec_edit.text()))
        sec_h.addWidget(self.copy_sec_btn)
        wb_layout.addLayout(sec_h)

        sec_note = QLabel("⚠️ Copy this secret now. It is masked immediately upon leaving this view.", self.webhook_box)
        sec_note.setStyleSheet("font-size: 11px; color: #F59E0B;")
        wb_layout.addWidget(sec_note)

        layout.addWidget(self.webhook_box)
        layout.addStretch()

        # Navigation
        btn_box = QHBoxLayout()
        back_btn = QPushButton("⏴ Back", page)
        back_btn.clicked.connect(lambda: self._advance_to_step(1))
        btn_box.addWidget(back_btn)

        btn_box.addStretch()

        self.step3_next_btn = QPushButton("Next: Verify Readiness ➔", page)
        self.step3_next_btn.setStyleSheet(
            "background-color: #2563EB; color: #FFFFFF; font-weight: 600; padding: 6px 16px; border-radius: 6px;"
        )
        self.step3_next_btn.clicked.connect(self._on_step3_next)
        btn_box.addWidget(self.step3_next_btn)

        layout.addLayout(btn_box)
        self.stack.addWidget(page)

    def _copy_to_clipboard(self, text: str) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self._show_info("Copied to clipboard!")

    def _on_webhook_cb_toggled(self, checked: bool) -> None:
        self.webhook_box.setEnabled(checked)

    def _prepare_webhook_step(self) -> None:
        """Create webhook connector if enabled and not already created."""
        if not self.enable_webhook_cb.isChecked() or self.webhook_connector:
            return
        if not self.created_project:
            return

        self._clear_status()
        self.progress_bar.show()

        def _worker():
            payload = {
                "project_id": self.created_project.project_id,
                "name": f"{self.created_project.name} Webhook Ingress",
                "connector_type": "webhook",
                "generate_secret": True,
                "config": {
                    "token_header": "X-Sentinel-Secret",
                },
            }
            conn = self.client.create_connector(payload)
            readiness = self.client.get_project_readiness(self.created_project.project_id)
            return conn, readiness

        def _on_success(res):
            conn, readiness = res
            self.progress_bar.hide()
            self.webhook_connector = conn
            self.readiness_status = readiness

            base_url = self.client.base_url
            # If external webhook ready or public ingress configured
            if readiness.external_webhook_ready:
                self.ingress_warn_banner.hide()
            else:
                self.ingress_warn_banner.show()

            ingest_path = f"{base_url}/connectors/{conn.connector_id}/ingest"
            self.webhook_url_edit.setText(ingest_path)
            self.webhook_sec_edit.setText(conn.raw_auth_secret or "sk-****")

        def _on_error(exc: Exception):
            self.progress_bar.hide()
            self._show_error(f"Failed to configure webhook connector: {exc}")

        self.task_runner.run(_worker, on_success=_on_success, on_error=_on_error)

    def _on_step3_next(self) -> None:
        self._advance_to_step(3)

    # -------------------------------------------------------------------------
    # STEP 4: Readiness Verification & Finish Setup
    # -------------------------------------------------------------------------
    def _init_step4_readiness(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        desc = QLabel(
            "Connection Summary: Review your live application readiness before opening the dashboard.",
            page,
        )
        desc.setStyleSheet("color: #94A3B8; font-size: 13px;")
        layout.addWidget(desc)

        # Summary Cards
        summary_group = QGroupBox("Operational Readiness", page)
        sm_layout = QVBoxLayout(summary_group)
        sm_layout.setSpacing(10)

        self.r_source_lbl = QLabel("• Source & Knowledge Base: Verifying...", summary_group)
        self.r_source_lbl.setStyleSheet("font-size: 13px; color: #E2E8F0;")
        sm_layout.addWidget(self.r_source_lbl)

        self.r_health_lbl = QLabel("• Health Polling: Checking...", summary_group)
        self.r_health_lbl.setStyleSheet("font-size: 13px; color: #E2E8F0;")
        sm_layout.addWidget(self.r_health_lbl)

        self.r_telemetry_lbl = QLabel("• Application Telemetry: Checking...", summary_group)
        self.r_telemetry_lbl.setStyleSheet("font-size: 13px; color: #E2E8F0;")
        sm_layout.addWidget(self.r_telemetry_lbl)

        layout.addWidget(summary_group)
        layout.addStretch()

        # Finish Setup Buttons
        btn_box = QHBoxLayout()
        back_btn = QPushButton("⏴ Back", page)
        back_btn.clicked.connect(lambda: self._advance_to_step(2))
        btn_box.addWidget(back_btn)

        btn_box.addStretch()

        self.finish_btn = QPushButton("Finish Setup & Open Dashboard ✓", page)
        self.finish_btn.setStyleSheet(
            "background-color: #059669; color: #FFFFFF; font-weight: 700; padding: 8px 20px; border-radius: 6px; font-size: 14px;"
        )
        self.finish_btn.clicked.connect(self._on_finish_setup)
        btn_box.addWidget(self.finish_btn)

        layout.addLayout(btn_box)
        self.stack.addWidget(page)

    def _refresh_readiness_display(self) -> None:
        if not self.created_project:
            return

        self._clear_status()
        self.progress_bar.show()

        def _worker():
            return self.client.get_project_readiness(self.created_project.project_id)

        def _on_success(readiness: ProjectReadinessDTO):
            self.progress_bar.hide()
            self.readiness_status = readiness

            # Source
            if readiness.is_indexed:
                self.r_source_lbl.setText(f"✓ Source Connected & Indexed (Project ID: {readiness.project_id})")
                self.r_source_lbl.setStyleSheet("font-size: 13px; color: #34D399; font-weight: 600;")
            else:
                self.r_source_lbl.setText("⚠️ Source Connected (Indexing in progress or partial)")
                self.r_source_lbl.setStyleSheet("font-size: 13px; color: #FBBF24;")

            # Health
            if self.poller_connector or readiness.health_status in ("healthy", "unknown"):
                h_text = f"✓ Health Poller Active (Status: {readiness.health_status or 'configured'})"
                self.r_health_lbl.setText(h_text)
                self.r_health_lbl.setStyleSheet("font-size: 13px; color: #34D399; font-weight: 600;")
            else:
                self.r_health_lbl.setText("• Health Poller: None configured")
                self.r_health_lbl.setStyleSheet("font-size: 13px; color: #94A3B8;")

            # Telemetry
            rel_time = _format_relative_time(readiness.last_telemetry_at)
            if readiness.telemetry_receiving:
                self.r_telemetry_lbl.setText(f"✓ Telemetry Receiving (Last activity: {rel_time})")
                self.r_telemetry_lbl.setStyleSheet("font-size: 13px; color: #34D399; font-weight: 600;")
            elif self.webhook_connector:
                if readiness.external_webhook_ready:
                    self.r_telemetry_lbl.setText(f"• Ingress Webhook Configured ({rel_time})")
                    self.r_telemetry_lbl.setStyleSheet("font-size: 13px; color: #38BDF8;")
                else:
                    self.r_telemetry_lbl.setText("⚠️ Ingress Webhook Configured (External Ingress Required)")
                    self.r_telemetry_lbl.setStyleSheet("font-size: 13px; color: #F59E0B;")
            else:
                self.r_telemetry_lbl.setText("• Application Telemetry: Not enabled")
                self.r_telemetry_lbl.setStyleSheet("font-size: 13px; color: #94A3B8;")

        def _on_error(exc: Exception):
            self.progress_bar.hide()
            self._show_error(f"Failed to fetch readiness status: {exc}")

        self.task_runner.run(_worker, on_success=_on_success, on_error=_on_error)

    def _on_finish_setup(self) -> None:
        if self.created_project:
            app_signals.active_project_changed.emit(self.created_project.project_id)
            app_signals.action_succeeded.emit(
                "Onboarding Complete",
                f"Application '{self.created_project.name}' is now active and monitored.",
            )
        self.accept()

    def _advance_to_step(self, step: int) -> None:
        self._clear_status()
        self.stack.setCurrentIndex(step)
        steps = [
            "Step 1 of 4: Project Source",
            "Step 2 of 4: Deployment & Health Polling",
            "Step 3 of 4: Telemetry Webhook Ingress",
            "Step 4 of 4: Readiness Verification",
        ]
        self.step_label.setText(steps[step])

        if step == 2:
            self._prepare_webhook_step()
        elif step == 3:
            self._refresh_readiness_display()
