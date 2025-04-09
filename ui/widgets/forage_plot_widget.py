"""
Forage Plot Widget for DSSAT Viewer
Specialized for FORAGE.OUT file visualization
"""
import os
import sys
import logging
from typing import List, Dict, Any

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, 
    QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor

# Add project root to path
project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_dir)

import config
from utils.dssat_paths import get_crop_details
from data.dssat_io import read_forage_file
from data.data_processing import get_variable_info
from models.metrics import MetricsCalculator

# Configure logging
logger = logging.getLogger(__name__)

class ForagePlotWidget(QWidget):
    """
    Custom widget for FORAGE.OUT file bar plot visualization using PyQtGraph
    
    Provides specialized display of forage data with bar charts.
    """
    
    # Signal when metrics are calculated
    metrics_calculated = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
        # Store data
        self.forage_data = None
    
    def setup_ui(self):
        """Setup the UI components"""
        # Main layout
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        
        # Create plot area
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')  # White background
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.plot_widget.setMinimumSize(400, 300)  # Set minimum size
        self.plot_widget.setMouseEnabled(x=True, y=True)  # Enable mouse interaction
        self.plot_widget.enableAutoRange()  # Enable auto-ranging
        
        # Add plot widget to main layout
        main_layout.addWidget(self.plot_widget)
        
        # Add a label for debugging
        self.debug_label = QLabel()
        self.debug_label.setStyleSheet("color: red;")
        main_layout.addWidget(self.debug_label)
    
    def plot_forage_data(self, 
                         selected_folder: str,
                         selected_treatments: List[str],
                         x_var: str,
                         y_vars: List[str],
                         treatment_names: Dict[str, str] = None):
        """
        Create bar plots from FORAGE.OUT data - simplified version
        
        Args:
            selected_folder: Selected crop folder
            selected_treatments: List of selected treatments
            x_var: X-axis variable (typically DATE or DOY)
            y_vars: List of Y-axis variables to plot
            treatment_names: Dictionary mapping treatment numbers to names
        """
        logger.info(f"Plotting forage data with folder: {selected_folder}")
        logger.info(f"X var: {x_var}, Y vars: {y_vars}")
        logger.info(f"Selected treatments: {selected_treatments}")
        
        # Clear previous plot and debug label
        self.plot_widget.clear()
        self.debug_label.clear()
        
        # Get crop directory
        crop_details = get_crop_details()
        crop_info = next(
            (crop for crop in crop_details 
            if crop['name'].upper() == selected_folder.upper()),
            None
        )
        
        if not crop_info:
            error_msg = f"Could not find crop info for: {selected_folder}"
            logger.error(error_msg)
            self.debug_label.setText(error_msg)
            return
            
        # Construct file path for FORAGE.OUT
        forage_path = os.path.join(crop_info['directory'], "FORAGE.OUT")
        if not os.path.exists(forage_path):
            error_msg = f"FORAGE.OUT not found at: {forage_path}"
            logger.warning(error_msg)
            self.debug_label.setText(error_msg)
            return
            
        # Read FORAGE.OUT data
        self.forage_data = read_forage_file(forage_path)
        if self.forage_data is None or self.forage_data.empty:
            error_msg = "No forage data available"
            logger.warning(error_msg)
            self.debug_label.setText(error_msg)
            return
            
        # Basic data cleaning
        self.forage_data = self.forage_data.dropna(axis=1, how='all')
        self.forage_data = self.forage_data.fillna(0)
            
        logger.info(f"Forage data loaded with columns: {self.forage_data.columns.tolist()}")
        logger.info(f"Data sample: {self.forage_data.head().to_string()}")
        
        # Filter to selected treatments
        if selected_treatments:
            # Make sure TRT column exists
            if "TRT" not in self.forage_data.columns and "TRNO" in self.forage_data.columns:
                self.forage_data["TRT"] = self.forage_data["TRNO"]
                
            try:
                # Convert selected_treatments to same type as TRT column for comparison
                numeric_treatments = [float(t) if t.isdigit() else t for t in selected_treatments]
                self.forage_data = self.forage_data[self.forage_data["TRT"].isin(numeric_treatments)]
            except Exception as e:
                logger.error(f"Error filtering treatments: {e}")
                # Try string comparison as fallback
                self.forage_data = self.forage_data[self.forage_data["TRT"].astype(str).isin(selected_treatments)]
            
        if self.forage_data.empty:
            error_msg = "No data for selected treatments"
            logger.warning(error_msg)
            self.debug_label.setText(error_msg)
            return
            
        # Ensure all variables exist
        for var in y_vars + [x_var]:
            if var not in self.forage_data.columns:
                error_msg = f"Variable {var} not found in forage data"
                logger.warning(error_msg)
                self.debug_label.setText(error_msg)
                return
                
        # Set basic plot labels
        self.plot_widget.setTitle("Forage Output Data")
        self.plot_widget.setLabel('bottom', x_var)
        self.plot_widget.setLabel('left', ", ".join(y_vars))
        
        # Get unique treatments and x values
        treatments = sorted(self.forage_data["TRT"].unique())
        x_values = sorted(self.forage_data[x_var].unique())
        
        logger.info(f"Treatments: {treatments}")
        logger.info(f"X values: {x_values}")
        
        # Calculate bar width and positions
        n_groups = len(x_values)
        n_bars_per_group = len(treatments) * len(y_vars)
        group_width = 0.8
        bar_width = group_width / n_bars_per_group if n_bars_per_group > 0 else 0.8
        
        logger.info(f"n_groups: {n_groups}, n_bars_per_group: {n_bars_per_group}, bar_width: {bar_width}")
        
        # Create color mapping for treatments
        colors = config.PLOT_COLORS if hasattr(config, 'PLOT_COLORS') else ['r', 'g', 'b', 'c', 'm', 'y', 'k']
        treatment_colors = {}
        for i, trt in enumerate(treatments):
            treatment_colors[trt] = colors[i % len(colors)]
        
        # Create x-axis tick positions and labels
        x_ticks = []
        
        # Plot bars for each x value, treatment, and variable
        try:
            for x_idx, x_val in enumerate(x_values):
                # Filter data for this x value
                x_data = self.forage_data[self.forage_data[x_var] == x_val]
                
                # Skip if no data for this x value
                if x_data.empty:
                    continue
                
                # Add x-tick
                x_ticks.append((x_idx, str(x_val)))
                
                # Plot bars for each treatment and variable
                bar_idx = 0
                for var_idx, var in enumerate(y_vars):
                    for trt_idx, trt in enumerate(treatments):
                        # Filter data for this treatment
                        trt_data = x_data[x_data["TRT"] == trt]
                        
                        if trt_data.empty:
                            bar_idx += 1
                            continue
                        
                        # Calculate bar position within group
                        bar_pos = x_idx + (bar_idx - n_bars_per_group/2 + 0.5) * bar_width
                        
                        # Get value for this variable
                        try:
                            # Convert to numeric and calculate mean
                            trt_data[var] = pd.to_numeric(trt_data[var], errors='coerce')
                            val = trt_data[var].mean()
                            if pd.isna(val):
                                bar_idx += 1
                                continue
                        except Exception as e:
                            logger.warning(f"Error calculating mean for {var} in treatment {trt}: {e}")
                            bar_idx += 1
                            continue
                        
                        # Debug output
                        logger.info(f"Bar: x={bar_pos}, height={val}, trt={trt}, var={var}")
                        
                        # Create bar
                        bar_color = treatment_colors[trt]
                        bar = pg.BarGraphItem(
                            x=[bar_pos], 
                            height=[val], 
                            width=bar_width,
                            brush=pg.mkBrush(bar_color)
                        )
                        self.plot_widget.addItem(bar)
                        
                        bar_idx += 1
        except Exception as e:
            error_msg = f"Error creating bars: {e}"
            logger.error(error_msg)
            self.debug_label.setText(error_msg)
            import traceback
            logger.error(traceback.format_exc())
        
        # Set x-axis ticks
        if x_ticks:
            try:
                x_axis = self.plot_widget.getAxis('bottom')
                x_axis.setTicks([x_ticks])
            except Exception as e:
                logger.error(f"Error setting x-axis ticks: {e}")
        
        # Set plot ranges
        if n_groups > 0:
            try:
                self.plot_widget.setXRange(-0.5, len(x_values) - 0.5)
            except Exception as e:
                logger.error(f"Error setting x range: {e}")
        
        # Enable auto range for y-axis
        try:
            self.plot_widget.enableAutoRange(axis='y')
        except Exception as e:
            logger.error(f"Error enabling y autorange: {e}")
        
        # Output debug info
        self.debug_label.setText(f"Plotted {n_bars_per_group} bars across {n_groups} groups")