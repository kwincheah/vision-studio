"""Plugin Manager & Extension Marketplace Dialog for Vision Master Clone.

Provides operators and third-party developers with:
1. Installed Plugins Manager (Inspect, Load from local folder, Package .vmpkg, Unload)
2. Community Marketplace (Browse curated plugins, Search, Filter, Install directly)
3. Direct GitHub Repository Installer (Install directly from GitHub repo URL or branch)
4. Plugin Creator & Scaffolder (Generate complete GitHub-ready plugin repositories)
"""
import os
import logging
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QPushButton, QGroupBox, QFileDialog, QMessageBox,
    QTextEdit, QWidget, QTabWidget, QLineEdit, QComboBox, QFormLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QColor, QDesktopServices

from vm_clone.sdk.manager import PluginManager, PluginState
from vm_clone.sdk.marketplace import MarketplaceService
from vm_clone.ui.styles import THEME

logger = logging.getLogger("vm_clone.plugins_ui")


class PluginManagerDialog(QDialog):
    """UI Dialog for managing installed plugins, exploring marketplace, and installing from GitHub."""

    plugins_changed = pyqtSignal()

    def __init__(self, parent=None, initial_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Extension Platform - Vision Master Studio")
        self.resize(880, 560)
        self.setMinimumSize(780, 480)

        self.plugin_manager = PluginManager.get_instance()
        self.marketplace_service = MarketplaceService.get_instance()
        self._suppress_msgbox = False

        self._init_ui()
        self._populate_table()
        self._populate_marketplace()

        if 0 <= initial_tab < self.tabs.count():
            self.tabs.setCurrentIndex(initial_tab)

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        # Tab widget hosting all extension functionality
        self.tabs = QTabWidget()
        self.tabs.setObjectName("pluginManagerTabs")

        # Tab 1: Installed Plugins
        tab_installed = self._build_installed_tab()
        self.tabs.addTab(tab_installed, "Installed Plugins")

        # Tab 2: Community Marketplace
        tab_marketplace = self._build_marketplace_tab()
        self.tabs.addTab(tab_marketplace, "Community Marketplace")

        # Tab 3: GitHub Installer
        tab_github = self._build_github_installer_tab()
        self.tabs.addTab(tab_github, "Install from GitHub")

        # Tab 4: Plugin Creator / Scaffold
        tab_creator = self._build_creator_tab()
        self.tabs.addTab(tab_creator, "Create && Publish")

        root_layout.addWidget(self.tabs, 1)

        # Footer Dialog Buttons
        footer = QHBoxLayout()
        hint = QLabel("Plugins run as modular extensions inside the Vision Master DAG pipeline.")
        hint.setStyleSheet(f"color: {THEME['text_muted']}; font-size: 12px;")
        footer.addWidget(hint, 1)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close, 0)
        root_layout.addLayout(footer, 0)

    # =========================================================================
    # Tab 1: Installed Plugins View
    # =========================================================================

    def _build_installed_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: Plugin Table & action buttons
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.table_plugins = QTableWidget(0, 4)
        self.table_plugins.setHorizontalHeaderLabels(["Plugin Name", "Version", "Category", "Status"])
        self.table_plugins.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_plugins.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_plugins.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_plugins.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_plugins.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_plugins.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_plugins.setAlternatingRowColors(True)
        self.table_plugins.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.table_plugins, 1)

        btn_bar = QHBoxLayout()
        self.btn_load_folder = QPushButton("Load from Folder...")
        self.btn_load_folder.clicked.connect(self._on_load_folder_clicked)
        btn_bar.addWidget(self.btn_load_folder)

        self.btn_rescan = QPushButton("Rescan Plugins")
        self.btn_rescan.clicked.connect(self._on_rescan_clicked)
        btn_bar.addWidget(self.btn_rescan)

        self.btn_unload = QPushButton("Unload Selected")
        self.btn_unload.clicked.connect(self._on_unload_clicked)
        btn_bar.addWidget(self.btn_unload)

        self.btn_package = QPushButton("Package .vmpkg...")
        self.btn_package.clicked.connect(self._on_package_clicked)
        btn_bar.addWidget(self.btn_package)

        left_layout.addLayout(btn_bar)
        splitter.addWidget(left_widget)

        # Right panel: Metadata inspector
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        grp_details = QGroupBox("Plugin Details && Exported Tools")
        grp_layout = QVBoxLayout(grp_details)
        grp_layout.setContentsMargins(8, 8, 8, 8)

        self.txt_details = QTextEdit()
        self.txt_details.setReadOnly(True)
        self.txt_details.setStyleSheet(f"""
            background-color: {THEME['bg_control']};
            color: {THEME['text_primary']};
            border: 1px solid {THEME['border_control']};
            font-family: Consolas, monospace;
            font-size: 12px;
        """)
        grp_layout.addWidget(self.txt_details)
        right_layout.addWidget(grp_details)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 5)

        layout.addWidget(splitter, 1)
        return widget

    def _populate_table(self):
        plugins = self.plugin_manager.list_plugins()
        self.table_plugins.setRowCount(len(plugins))

        for r, p in enumerate(plugins):
            item_name = QTableWidgetItem(p.metadata.name)
            item_name.setData(Qt.ItemDataRole.UserRole, p.metadata.plugin_id)
            item_ver = QTableWidgetItem(f"v{p.metadata.version}")
            item_cat = QTableWidgetItem(p.metadata.category)
            item_status = QTableWidgetItem(p.state)

            if p.state == PluginState.LOADED:
                item_status.setForeground(QColor(THEME["status_ok_text"]))
            elif p.state == PluginState.ERROR or p.state == PluginState.INCOMPATIBLE:
                item_status.setForeground(QColor(THEME["status_error_text"]))
            else:
                item_status.setForeground(QColor(THEME["text_secondary"]))

            self.table_plugins.setItem(r, 0, item_name)
            self.table_plugins.setItem(r, 1, item_ver)
            self.table_plugins.setItem(r, 2, item_cat)
            self.table_plugins.setItem(r, 3, item_status)

        if plugins:
            self.table_plugins.selectRow(0)
        else:
            self.txt_details.setPlainText("No third-party plugins loaded.")

    def _on_selection_changed(self):
        rows = self.table_plugins.selectionModel().selectedRows()
        if not rows:
            self.txt_details.clear()
            return
        row = rows[0].row()
        item = self.table_plugins.item(row, 0)
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        p = self.plugin_manager.get_plugin(pid)
        if not p:
            return

        tool_lines = "\n".join([f"  - {t.tool_name} [{getattr(t, 'category', 'Custom')}]" for t in p.tools])
        if not tool_lines:
            tool_lines = "  (None)"

        details = f"""Plugin ID:     {p.metadata.plugin_id}
Name:          {p.metadata.name}
Version:       {p.metadata.version}
Author:        {p.metadata.author}
Category:      {p.metadata.category}
Status:        {p.state}
SDK Version:   Requires >= {p.metadata.min_sdk_version}
License:       {p.metadata.license}
Directory:     {p.directory_path}

Description:
{p.metadata.description or 'No description provided.'}

Exported Tools ({len(p.tools)}):
{tool_lines}
"""
        if p.error_message:
            details += f"\nErrors / Warnings:\n  {p.error_message}\n"

        self.txt_details.setPlainText(details)

    def _on_load_folder_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Plugin Directory", "")
        if folder:
            rec = self.plugin_manager.load_plugin_from_directory(folder, reload=True)
            if rec and rec.state == PluginState.LOADED:
                if not self._suppress_msgbox:
                    QMessageBox.information(
                        self, "Plugin Loaded",
                        f"Successfully loaded plugin '{rec.metadata.name}' with {len(rec.tools)} tool(s)."
                    )
                self.plugins_changed.emit()
            elif rec:
                if not self._suppress_msgbox:
                    QMessageBox.warning(
                        self, "Plugin Warning",
                        f"Plugin '{rec.metadata.name}' loaded with status: {rec.state}\n{rec.error_message}"
                    )
            else:
                if not self._suppress_msgbox:
                    QMessageBox.critical(self, "Load Error", "Selected folder does not contain a valid plugin manifest or entrypoint.")
            self._populate_table()
            self._populate_marketplace()

    def _on_rescan_clicked(self):
        self.plugin_manager.discover_and_load_all(reload=True)
        self._populate_table()
        self._populate_marketplace()
        self.plugins_changed.emit()
        if not self._suppress_msgbox:
            QMessageBox.information(self, "Rescan Complete", "Plugin discovery rescan completed.")

    def _on_unload_clicked(self):
        rows = self.table_plugins.selectionModel().selectedRows()
        if not rows:
            return
        pid = self.table_plugins.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        should_unload = True
        if not self._suppress_msgbox:
            confirm = QMessageBox.question(
                self, "Confirm Unload",
                f"Are you sure you want to unload plugin '{pid}'? Its tools will be removed from the palette.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            should_unload = (confirm == QMessageBox.StandardButton.Yes)

        if should_unload:
            self.plugin_manager.unload_plugin(pid)
            self._populate_table()
            self._populate_marketplace()
            self.txt_details.clear()
            self.plugins_changed.emit()

    def _on_package_clicked(self):
        rows = self.table_plugins.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "Package Error", "Please select a plugin to package.")
            return
        pid = self.table_plugins.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        p = self.plugin_manager.get_plugin(pid)
        if not p or not os.path.exists(p.directory_path):
            QMessageBox.warning(self, "Package Error", "Selected plugin directory is invalid.")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Distributable Plugin Package",
            os.path.join(os.path.dirname(p.directory_path), f"{pid}.vmpkg"),
            "Vision Master Plugin Package (*.vmpkg);;ZIP Archive (*.zip)"
        )
        if save_path:
            ok, msg, out_file = self.marketplace_service.package_plugin(p.directory_path, save_path)
            if ok:
                if not self._suppress_msgbox:
                    QMessageBox.information(self, "Package Created", f"Plugin packaged successfully:\n{out_file}\n\nReady for distribution or GitHub Releases!")
            else:
                if not self._suppress_msgbox:
                    QMessageBox.critical(self, "Package Error", msg)

    # =========================================================================
    # Tab 2: Community Marketplace
    # =========================================================================

    def _build_marketplace_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Search & Filter bar
        filter_bar = QHBoxLayout()
        lbl_search = QLabel("Search:")
        filter_bar.addWidget(lbl_search)

        self.txt_market_search = QLineEdit()
        self.txt_market_search.setPlaceholderText("Search community plugins by name, tag, or description...")
        self.txt_market_search.textChanged.connect(self._populate_marketplace)
        filter_bar.addWidget(self.txt_market_search, 1)

        lbl_cat = QLabel("Category:")
        filter_bar.addWidget(lbl_cat)

        self.combo_market_category = QComboBox()
        self.combo_market_category.addItems([
            "All", "Custom Filters", "Image Processing", "Measurement", "Recognition", "Color Processing"
        ])
        self.combo_market_category.currentTextChanged.connect(self._populate_marketplace)
        filter_bar.addWidget(self.combo_market_category)

        btn_refresh = QPushButton("Refresh Catalog")
        btn_refresh.clicked.connect(lambda: self._populate_marketplace(refresh_catalog=True))
        filter_bar.addWidget(btn_refresh)

        layout.addLayout(filter_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Marketplace catalog table
        self.table_marketplace = QTableWidget(0, 5)
        self.table_marketplace.setHorizontalHeaderLabels(["Plugin Name", "Version", "Author", "Category", "Status"])
        self.table_marketplace.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_marketplace.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_marketplace.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table_marketplace.setColumnWidth(2, 130)
        self.table_marketplace.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table_marketplace.setColumnWidth(3, 110)
        self.table_marketplace.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_marketplace.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_marketplace.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_marketplace.setAlternatingRowColors(True)
        self.table_marketplace.itemSelectionChanged.connect(self._on_market_selection_changed)
        splitter.addWidget(self.table_marketplace)

        # Right panel: Marketplace details & Install action
        market_right = QWidget()
        mr_layout = QVBoxLayout(market_right)
        mr_layout.setContentsMargins(0, 0, 0, 0)
        mr_layout.setSpacing(6)

        grp_market = QGroupBox("Extension Overview")
        gm_layout = QVBoxLayout(grp_market)
        gm_layout.setContentsMargins(8, 8, 8, 8)

        self.txt_market_details = QTextEdit()
        self.txt_market_details.setReadOnly(True)
        self.txt_market_details.setStyleSheet(f"""
            background-color: {THEME['bg_control']};
            color: {THEME['text_primary']};
            border: 1px solid {THEME['border_control']};
            font-family: Consolas, monospace;
            font-size: 12px;
        """)
        gm_layout.addWidget(self.txt_market_details)

        action_box = QHBoxLayout()
        self.btn_market_install = QPushButton("Install Plugin")
        self.btn_market_install.clicked.connect(self._on_market_install_clicked)
        action_box.addWidget(self.btn_market_install)

        self.btn_market_github = QPushButton("View on GitHub")
        self.btn_market_github.clicked.connect(self._on_market_view_github_clicked)
        action_box.addWidget(self.btn_market_github)

        gm_layout.addLayout(action_box)
        mr_layout.addWidget(grp_market)

        splitter.addWidget(market_right)
        splitter.setSizes([560, 360])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter, 1)
        return widget

    def _populate_marketplace(self, refresh_catalog: bool = False):
        query = self.txt_market_search.text()
        cat = self.combo_market_category.currentText()
        if refresh_catalog:
            self.marketplace_service.get_catalog(refresh=True)

        items = self.marketplace_service.search(query, cat if cat != "All" else None)
        self.table_marketplace.setRowCount(len(items))

        for r, item in enumerate(items):
            it_name = QTableWidgetItem(item.name)
            it_name.setData(Qt.ItemDataRole.UserRole, item.id)
            it_ver = QTableWidgetItem(f"v{item.version}")
            it_author = QTableWidgetItem(item.author)
            it_cat = QTableWidgetItem(item.category)

            status_str = "Installed" if item.is_installed else "Available"
            if item.has_update:
                status_str = "Update Available"

            it_status = QTableWidgetItem(status_str)
            if item.is_installed:
                it_status.setForeground(QColor(THEME["status_ok_text"]))
            elif item.has_update:
                it_status.setForeground(QColor(THEME["status_warn_text"]))
            else:
                it_status.setForeground(QColor(THEME["text_secondary"]))

            self.table_marketplace.setItem(r, 0, it_name)
            self.table_marketplace.setItem(r, 1, it_ver)
            self.table_marketplace.setItem(r, 2, it_author)
            self.table_marketplace.setItem(r, 3, it_cat)
            self.table_marketplace.setItem(r, 4, it_status)

        if items:
            self.table_marketplace.selectRow(0)
        else:
            self.txt_market_details.setPlainText("No extensions matching criteria.")

    def _on_market_selection_changed(self):
        rows = self.table_marketplace.selectionModel().selectedRows()
        if not rows:
            self.txt_market_details.clear()
            return
        row = rows[0].row()
        item_w = self.table_marketplace.item(row, 0)
        if not item_w:
            return
        pid = item_w.data(Qt.ItemDataRole.UserRole)
        catalog = self.marketplace_service.get_catalog()
        item = next((i for i in catalog if i.id == pid), None)
        if not item:
            return

        status_text = "Installed (Up to date)" if item.is_installed and not item.has_update else (
            f"Update available (Installed: v{item.installed_version})" if item.has_update else "Not installed"
        )

        details = f"""Plugin:        {item.name}
ID:            {item.id}
Version:       v{item.version}
Author:        {item.author}
Category:      {item.category}
Status:        {status_text}
Rating:        {'★' * 5} ({item.stars} GitHub stars, {item.downloads} downloads)
License:       {item.license}
GitHub Repo:   {item.github_url}
Tags:          {', '.join(item.tags)}

Overview:
{item.description}
"""
        self.txt_market_details.setPlainText(details)

        if item.is_installed and not item.has_update:
            self.btn_market_install.setText("Installed (Reinstall)")
        elif item.has_update:
            self.btn_market_install.setText("Update Plugin")
        else:
            self.btn_market_install.setText("Install Plugin")

    def _on_market_install_clicked(self):
        rows = self.table_marketplace.selectionModel().selectedRows()
        if not rows:
            return
        pid = self.table_marketplace.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        catalog = self.marketplace_service.get_catalog()
        item = next((i for i in catalog if i.id == pid), None)
        if not item:
            return

        # Install using GitHub URL
        ok, msg, rec = self.marketplace_service.install_from_github(item.github_url)
        if ok:
            if not self._suppress_msgbox:
                QMessageBox.information(self, "Installation Complete", msg)
            self._populate_table()
            self._populate_marketplace()
            self.plugins_changed.emit()
        else:
            if not self._suppress_msgbox:
                QMessageBox.warning(self, "Installation Result", f"Could not complete installation:\n{msg}")

    def _on_market_view_github_clicked(self):
        rows = self.table_marketplace.selectionModel().selectedRows()
        if not rows:
            return
        pid = self.table_marketplace.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        catalog = self.marketplace_service.get_catalog()
        item = next((i for i in catalog if i.id == pid), None)
        if item and item.github_url:
            QDesktopServices.openUrl(QUrl(item.github_url))

    # =========================================================================
    # Tab 3: Direct GitHub Installer
    # =========================================================================

    def _build_github_installer_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel(
            "Install a custom third-party vision plugin directly from any public GitHub repository.\n"
            "The repository must contain a 'plugin.json' manifest and an '__init__.py' entrypoint."
        )
        header.setStyleSheet(f"color: {THEME['text_secondary']}; font-size: 12px;")
        layout.addWidget(header)

        form_box = QGroupBox("GitHub Repository Settings")
        form_layout = QFormLayout(form_box)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setSpacing(8)

        self.txt_github_url = QLineEdit()
        self.txt_github_url.setPlaceholderText("e.g. https://github.com/username/my-vision-plugin or username/my-vision-plugin")
        form_layout.addRow("Repository URL:", self.txt_github_url)

        self.txt_github_branch = QLineEdit("main")
        self.txt_github_branch.setPlaceholderText("main, master, or release tag")
        form_layout.addRow("Branch / Ref:", self.txt_github_branch)

        btn_row = QHBoxLayout()
        self.btn_github_install = QPushButton("Download, Validate && Install")
        self.btn_github_install.setStyleSheet(f"font-weight: bold; padding: 6px {THEME['sp_section']}px; background-color: {THEME['accent_primary']}; color: {THEME['text_primary']}; border-radius: 4px;")
        self.btn_github_install.clicked.connect(self._on_direct_github_install_clicked)
        btn_row.addWidget(self.btn_github_install)
        btn_row.addStretch(1)
        form_layout.addRow("", btn_row)

        layout.addWidget(form_box)

        # Installation console log
        grp_log = QGroupBox("Installation Log")
        gl_layout = QVBoxLayout(grp_log)
        gl_layout.setContentsMargins(8, 8, 8, 8)

        self.txt_github_log = QTextEdit()
        self.txt_github_log.setReadOnly(True)
        self.txt_github_log.setStyleSheet(f"""
            background-color: {THEME['bg_control']};
            color: {THEME['text_primary']};
            border: 1px solid {THEME['border_control']};
            font-family: Consolas, monospace;
            font-size: 12px;
        """)
        self.txt_github_log.setPlainText("Ready to download and install plugin from GitHub.")
        gl_layout.addWidget(self.txt_github_log)
        layout.addWidget(grp_log, 1)

        return widget

    def _on_direct_github_install_clicked(self):
        url = self.txt_github_url.text().strip()
        branch = self.txt_github_branch.text().strip() or "main"

        if not url:
            QMessageBox.warning(self, "Input Error", "Please provide a valid GitHub repository URL.")
            return

        self.txt_github_log.append(f"\n[1/3] Parsing repository URL: {url} (branch: {branch})...")
        parsed = self.marketplace_service.parse_github_url(url)
        if not parsed:
            self.txt_github_log.append("  [ERROR] Invalid GitHub URL format. Use https://github.com/owner/repo")
            return

        self.txt_github_log.append(f"  Owner: {parsed[0]}, Repo: {parsed[1]}")
        self.txt_github_log.append("[2/3] Downloading archive and validating plugin structure...")

        ok, msg, record = self.marketplace_service.install_from_github(url, branch)
        if ok:
            self.txt_github_log.append(f"[3/3] Success! {msg}")
            if record:
                self.txt_github_log.append(f"  Registered {len(record.tools)} tool(s): {', '.join([t.tool_name for t in record.tools])}")
            if not self._suppress_msgbox:
                QMessageBox.information(self, "Installation Succeeded", msg)
            self._populate_table()
            self._populate_marketplace()
            self.plugins_changed.emit()
        else:
            self.txt_github_log.append(f"[ERROR] {msg}")
            if not self._suppress_msgbox:
                QMessageBox.warning(self, "Installation Failed", msg)

    # =========================================================================
    # Tab 4: Plugin Creator / Scaffold
    # =========================================================================

    def _build_creator_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel(
            "Scaffold a complete, ready-to-publish Vision Master plugin repository.\n"
            "Generates 'plugin.json', typed 'PluginToolBase' template, 'README.md', and '.gitignore' ready to push to GitHub."
        )
        header.setStyleSheet(f"color: {THEME['text_secondary']}; font-size: 12px;")
        layout.addWidget(header)

        form_box = QGroupBox("Plugin Specification")
        form_layout = QFormLayout(form_box)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setSpacing(8)

        self.txt_create_id = QLineEdit("my_custom_filter")
        self.txt_create_id.setPlaceholderText("Alphanumeric with underscores (e.g. adaptive_blur)")
        form_layout.addRow("Plugin ID:", self.txt_create_id)

        self.txt_create_name = QLineEdit("Adaptive Blur Filter")
        self.txt_create_name.setPlaceholderText("Display name of your plugin package")
        form_layout.addRow("Package Name:", self.txt_create_name)

        self.txt_create_author = QLineEdit("Developer")
        form_layout.addRow("Author / Org:", self.txt_create_author)

        self.combo_create_category = QComboBox()
        self.combo_create_category.addItems([
            "Custom Filters", "Image Processing", "Measurement", "Recognition", "Color Processing", "Defect Detection", "Location"
        ])
        form_layout.addRow("Category:", self.combo_create_category)

        self.txt_create_tool_name = QLineEdit("Adaptive Blur")
        self.txt_create_tool_name.setPlaceholderText("Name of the exported vision tool in the palette")
        form_layout.addRow("Primary Tool Name:", self.txt_create_tool_name)

        self.txt_create_desc = QLineEdit("High performance spatial adaptive filtering tool.")
        form_layout.addRow("Description:", self.txt_create_desc)

        dir_row = QHBoxLayout()
        self.txt_create_dest = QLineEdit(os.path.abspath("plugins"))
        dir_row.addWidget(self.txt_create_dest, 1)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._on_browse_create_dir)
        dir_row.addWidget(btn_browse, 0)
        form_layout.addRow("Output Folder:", dir_row)

        btn_create = QPushButton("Generate Plugin Scaffold")
        btn_create.setStyleSheet(f"font-weight: bold; padding: 6px {THEME['sp_section']}px; background-color: {THEME['accent_primary']}; color: {THEME['text_primary']}; border-radius: 4px;")
        btn_create.clicked.connect(self._on_generate_scaffold_clicked)
        form_layout.addRow("", btn_create)

        layout.addWidget(form_box)

        # Instructions on GitHub publishing
        grp_inst = QGroupBox("How to Publish to Your GitHub Repository")
        gi_layout = QVBoxLayout(grp_inst)
        gi_layout.setContentsMargins(8, 8, 8, 8)

        txt_instructions = QTextEdit()
        txt_instructions.setReadOnly(True)
        txt_instructions.setStyleSheet(f"""
            background-color: {THEME['bg_control']};
            color: {THEME['text_primary']};
            border: 1px solid {THEME['border_control']};
            font-family: Consolas, monospace;
            font-size: 12px;
        """)
        txt_instructions.setPlainText("""1. Generate the plugin scaffold above into your project or local workspace.
2. In your terminal, navigate into the generated plugin directory:
   cd plugins/<plugin_id>
3. Initialize git and commit:
   git init
   git add .
   git commit -m "Initial plugin commit"
4. Create a public repository on GitHub (e.g. https://github.com/your-username/my-vision-plugin).
5. Push to GitHub:
   git remote add origin https://github.com/your-username/my-vision-plugin.git
   git branch -M main
   git push -u origin main
6. Share your repository URL! Any user can now install it via the 'Install from GitHub' tab.
""")
        gi_layout.addWidget(txt_instructions)
        layout.addWidget(grp_inst, 1)

        return widget

    def _on_browse_create_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.txt_create_dest.text())
        if folder:
            self.txt_create_dest.setText(os.path.normpath(folder))

    def _on_generate_scaffold_clicked(self):
        pid = self.txt_create_id.text().strip()
        name = self.txt_create_name.text().strip()
        author = self.txt_create_author.text().strip()
        category = self.combo_create_category.currentText()
        tool_name = self.txt_create_tool_name.text().strip()
        desc = self.txt_create_desc.text().strip()
        dest_dir = self.txt_create_dest.text().strip()

        if not pid or not name or not tool_name:
            QMessageBox.warning(self, "Input Error", "Please provide a valid Plugin ID, Package Name, and Tool Name.")
            return

        ok, msg, created_path = self.marketplace_service.scaffold_plugin(
            dest_parent_dir=dest_dir,
            plugin_id=pid,
            name=name,
            author=author,
            category=category,
            tool_name=tool_name,
            description=desc
        )

        if ok:
            # If generated inside plugins directory, automatically load it
            if os.path.abspath(dest_dir) in [os.path.abspath(d) for d in self.plugin_manager.plugin_dirs]:
                self.plugin_manager.load_plugin_from_directory(created_path, reload=True)
                self._populate_table()
                self._populate_marketplace()
                self.plugins_changed.emit()

            if not self._suppress_msgbox:
                QMessageBox.information(
                    self, "Plugin Created",
                    f"{msg}\n\nAll manifest and template files have been generated.\nFollow the instructions below to publish to GitHub!"
                )
        else:
            if not self._suppress_msgbox:
                QMessageBox.critical(self, "Generation Failed", msg)
