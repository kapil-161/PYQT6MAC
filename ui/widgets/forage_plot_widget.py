"""
Forage Plot Widget for DSSAT Viewer
Specialized for FORAGE.OUT file visualization with bar plots
"""
import os
import sys
import logging
from typing import List, Dict, Any, Optional

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal

# Add project root to path
project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_dir)

import config
from utils.dssat_paths import get_crop_details
from data.dssat_io import read_file
from data.data_processing import get_variable_info

# Configure logging
logger = logging.getLogger(__name__)

class ForagePlotWidget(QWidget):
    """
    Custom widget for FORAGE.OUT file bar plot visualization using PyQtGraph
    """
    
    # Signal when metrics are calculated
    metrics_calculated = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.forage_data = None
        self.legend_items = {}  # Track legend items to avoid duplicates
    
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
        self.plot_widget.setMinimumSize(400, 300)
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.enableAutoRange()
        
        # Add plot widget to main layout
        main_layout.addWidget(self.plot_widget)
        
        # Debug label
        self.debug_label = QLabel()
        self.debug_label.setStyleSheet("color: red;")
        main_layout.addWidget(self.debug_label)

    def load_forage_data(self, selected_folder: str) -> bool:
        """Load FORAGE.OUT data for the selected folder"""
        # Get crop directory
        crop_details = get_crop_details()
        crop_info = next(
            (crop for crop in crop_details 
            if crop['name'].upper() == selected_folder.upper()),
            None
        )
        
        if not crop_info:
            self.debug_label.setText(f"Could not find crop info for: {selected_folder}")
            return False
            
        # Construct file path for FORAGE.OUT
        forage_path = os.path.join(crop_info['directory'], "FORAGE.OUT")
        if not os.path.exists(forage_path):
            self.debug_label.setText(f"FORAGE.OUT not found at: {forage_path}")
            return False
            
        # Read FORAGE.OUT data
        self.forage_data = read_file(forage_path)
        if self.forage_data is None or self.forage_data.empty:
            self.debug_label.setText("No forage data available")
            return False
            
        return True

    def prepare_data(self, selected_treatments: List[str]) -> bool:
        """Prepare and clean the data"""
        if self.forage_data is None:
            return False
            
        # Handle categorical and numeric columns
        categorical_cols = self.forage_data.select_dtypes(include=['category']).columns
        numeric_cols = self.forage_data.select_dtypes(include=np.number).columns
        
        # Drop columns that are all NA
        self.forage_data = self.forage_data.dropna(axis=1, how='all')
        
        # Fill NA in numeric columns with 0
        if len(numeric_cols) > 0:
            self.forage_data[numeric_cols] = self.forage_data[numeric_cols].fillna(0)
            
        # For categorical columns, fill NA with first category
        for col in categorical_cols:
            if self.forage_data[col].isna().any():
                first_category = self.forage_data[col].cat.categories[0]
                self.forage_data[col] = self.forage_data[col].fillna(first_category)
        
        # Ensure TRT column exists and is properly formatted
        if "TRT" not in self.forage_data.columns and "TRNO" in self.forage_data.columns:
            self.forage_data["TRT"] = self.forage_data["TRNO"].astype(str)
        
        self.forage_data["TRT"] = self.forage_data["TRT"].astype(str)
        
        # Filter to selected treatments
        if selected_treatments:
            str_treatments = [str(t) for t in selected_treatments]
            self.forage_data = self.forage_data[self.forage_data["TRT"].isin(str_treatments)]
            
        return not self.forage_data.empty

    def plot_data(self, x_var: str, y_vars: List[str], treatment_names: Optional[Dict[str, str]] = None):
        """Plot the data with currently selected variables"""
        if self.forage_data is None or self.forage_data.empty:
            self.debug_label.setText("No data available")
            return
        
        if not y_vars:
            self.debug_label.setText("No variables selected for plotting")
            return

        # Ensure x_var exists in data
        if x_var not in self.forage_data.columns:
            self.debug_label.setText(f"X-axis variable {x_var} not found in data")
            return
            
        # First remove all plot items and legend
        self.plot_widget.clear()
        if hasattr(self, 'legend'):
            self.plot_widget.removeItem(self.legend)
            delattr(self, 'legend')
        
        # Create fresh legend
        self.legend = self.plot_widget.addLegend()
        
        # Get x label info
        x_label, _ = get_variable_info(x_var)
        x_display = x_label or x_var
        
        # Set plot labels
        self.plot_widget.setTitle("Forage Output Data")
        self.plot_widget.setLabel('bottom', x_display)
        
        # Get y label info
        y_labels = []
        for var in y_vars:
            var_label, _ = get_variable_info(var)
            y_labels.append(var_label or var)
        self.plot_widget.setLabel('left', ", ".join(y_labels))
        
        # Get unique treatments and x values
        treatments = sorted(self.forage_data["TRT"].unique())
        x_values = sorted(self.forage_data[x_var].unique())
        
        # Format x values if they're dates
        if x_var == "DATE":
            x_labels = [pd.Timestamp(x).strftime('%Y-%m-%d') for x in x_values]
        else:
            x_labels = [str(x) for x in x_values]
        
        # Create tick positions and labels
        x_ticks = [(i, x_labels[i]) for i in range(len(x_values))]
        
        # Create color mapping for treatments
        colors = config.PLOT_COLORS if hasattr(config, 'PLOT_COLORS') else ['r', 'g', 'b', 'c', 'm', 'y', 'k']
        treatment_colors = {}
        for i, trt in enumerate(treatments):
            treatment_colors[trt] = colors[i % len(colors)]
        
        try:
            # Calculate bar width considering number of treatments and variables
            n_active_vars = len([v for v in y_vars if v != x_var])  # Count only active variables
            if n_active_vars == 0:
                self.debug_label.setText("No valid variables to plot")
                return
                
            group_width = 0.8  # Width for entire group of bars
            bar_width = group_width / (len(treatments) * n_active_vars)
            
            # Convert x variable to numeric if needed
            if x_var != "DATE":
                self.forage_data[x_var] = pd.to_numeric(self.forage_data[x_var], errors='coerce')
            
            active_var_idx = 0  # Track position for active variables only
            
            for trt_idx, trt in enumerate(treatments):
                # Get treatment display name
                trt_name = treatment_names.get(trt, f"Treatment {trt}") if treatment_names else f"Treatment {trt}"
                
                # Filter data for this treatment
                trt_data = self.forage_data[self.forage_data["TRT"] == trt]
                if trt_data.empty:
                    continue
                
                for var in y_vars:
                    # Skip if trying to plot x variable against itself
                    if var == x_var:
                        continue
                        
                    bar_positions = []
                    bar_heights = []
                    
                    # Calculate offset for grouped bars
                    combined_idx = trt_idx * n_active_vars + active_var_idx
                    bar_offset = (combined_idx - (len(treatments) * n_active_vars)/2 + 0.5) * bar_width
                    
                    for x_idx, x_val in enumerate(x_values):
                        # Filter to current x value
                        x_data = trt_data[trt_data[x_var] == x_val]
                        
                        if x_data.empty:
                            continue
                        
                        # Calculate position and height
                        bar_pos = x_idx + bar_offset
                        bar_positions.append(bar_pos)
                        
                        try:
                            x_data[var] = pd.to_numeric(x_data[var], errors='coerce')
                            val = x_data[var].mean()
                            bar_heights.append(val if not pd.isna(val) else 0)
                        except Exception as e:
                            logger.warning(f"Error calculating {var} for treatment {trt} at x={x_val}: {e}")
                            bar_heights.append(0)
                    
                    # Only create bars if we have data
                    if bar_positions and bar_heights:
                        # Get variable display name
                        var_label, _ = get_variable_info(var)
                        var_display = var_label or var
                        
                        # Create legend name
                        if len(y_vars) > 1:
                            legend_name = f"{trt_name} - {var_display}"
                        else:
                            legend_name = trt_name
                        
                        # Create bar graph
                        bar_color = treatment_colors[trt]
                        bg = pg.BarGraphItem(
                            x=bar_positions, 
                            height=bar_heights, 
                            width=bar_width,
                            brush=pg.mkBrush(bar_color),
                            name=legend_name
                        )
                        self.plot_widget.addItem(bg)
                        
                        # Add to legend
                        self.legend.addItem(bg, legend_name)
                    
                    active_var_idx += 1  # Increment only for active variables
            
            # Set x-axis ticks
            if x_ticks:
                x_axis = self.plot_widget.getAxis('bottom')
                x_axis.setTicks([x_ticks])
            
            # Set plot ranges
            if len(x_values) > 0:
                self.plot_widget.setXRange(-0.5, len(x_values) - 0.5)
            
            # Enable auto range for y-axis
            self.plot_widget.enableAutoRange(axis='y')
            
            # Update debug label
            self.debug_label.setText(
                f"Plotted {n_active_vars} variables for {len(treatments)} treatments across {len(x_values)} points"
            )
            
        except Exception as e:
            error_msg = f"Error creating plot: {e}"
            logger.error(error_msg)
            self.debug_label.setText(error_msg)
            import traceback
            logger.error(traceback.format_exc())

    def plot_forage_data(self, 
                         selected_folder: str,
                         selected_treatments: List[str],
                         x_var: str = "DATE",
                         y_vars: List[str] = ["BAR"],
                         treatment_names: Optional[Dict[str, str]] = None):
        """Main entry point for plotting forage data"""
        # Load and prepare data
        if not self.load_forage_data(selected_folder):
            return
            
        if not self.prepare_data(selected_treatments):
            return
            
        # Plot the data
        self.plot_data(x_var, y_vars, treatment_names)