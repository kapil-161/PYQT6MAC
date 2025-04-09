import sys
import os
import pandas as pd
# Add project root to Python path
project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_dir)

"""
DSSAT file I/O operations
"""
import os
import glob
# OPTIMIZED: Import only necessary pandas components
from pandas import DataFrame, concat, to_datetime, to_numeric, isna
# OPTIMIZED: Import only necessary numpy components
from numpy import nan
import logging
import subprocess
from typing import List, Optional
import config
from data.data_processing import standardize_dtypes, unified_date_convert
from utils.dssat_paths import get_crop_details

logger = logging.getLogger(__name__)

def prepare_experiment(selected_folder: str) -> List[tuple]:
    """List available experiments based on selected folder."""
    try:
        # Get crop details for directory and code
        logger.info(f"Preparing experiments for folder: {selected_folder}")
        crop_details = get_crop_details()
        crop_info = next(
            (crop for crop in crop_details 
             if crop['name'].upper() == selected_folder.upper()),
            None
        )
        
        if not crop_info:
            logger.error(f"Could not find crop information for folder {selected_folder}")
            return []
            
        # Use directory from crop_info
        folder_path = crop_info['directory'].strip()
        logger.info(f"Using directory path: {folder_path}")
        if not folder_path:
            logger.error(f"No directory found for crop {selected_folder}")
            return []
            
        # Find X files using crop code
        x_file_pattern = f"*.{crop_info['code']}X"
        logger.info(f"Looking for experiment files with pattern: {x_file_pattern}")
        x_files = glob.glob(os.path.join(folder_path, x_file_pattern))
        logger.info(f"Found {len(x_files)} experiment files: {x_files}")
        
        result = []
        for file_path in x_files:
            filename = os.path.basename(file_path)
            exp_detail = filename  # Default to filename
            
            # Try to read experiment title from file
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    for line in file:
                        if "*EXP.DETAILS:" in line:
                            # Extract the title from the line
                            detail_part = line.strip().split("*EXP.DETAILS:")[1].strip()
                            exp_detail = ' '.join(detail_part.split()[1:])
                            logger.info(f"Found experiment details for {filename}: {exp_detail}")
                            break
            except Exception as e:
                logger.warning(f"Could not read experiment details from {filename}: {e}")
            
            # Add tuple of (display_name, filename) to the result
            result.append((exp_detail, filename))
            logger.info(f"Added experiment: {exp_detail} ({filename})")
        
        logger.info(f"Returning {len(result)} experiments")
        return result
        
    except Exception as e:
        logger.error(f"Error preparing experiments: {str(e)}", exc_info=True)
        return []
def read_forage_file(file_path: str) -> Optional[DataFrame]:
    """Read and process FORAGE.OUT file with flexible column handling."""
    try:
        # Normalize the file path to ensure the correct format
        file_path = os.path.normpath(file_path)
        logger.info(f"Reading FORAGE.OUT file: {file_path}")
        
        if not os.path.exists(file_path):
            logger.error(f"File does not exist: {file_path}")
            return None

        # Read file with efficient encoding handling
        encodings = ['utf-8', 'latin-1']
        lines = None
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as file:
                    lines = file.readlines()
                break
            except UnicodeDecodeError:
                continue

        if not lines:
            logger.error(f"Could not read file with any encoding: {file_path}")
            return None

        # Process data more efficiently
        data_frames = []
        
        # Find all header lines (starting with @ or *)
        header_indices = [i for i, line in enumerate(lines) 
                         if line.strip().startswith("@") or 
                            (line.strip().startswith("*") and "YEAR" in line)]
        
        if not header_indices:
            logger.error("No header line found in FORAGE.OUT file")
            return None
            
        # Process each data block
        for idx, start_idx in enumerate(header_indices):
            next_idx = header_indices[idx + 1] if idx + 1 < len(header_indices) else len(lines)
            
            # Get header line and extract column names
            header_line = lines[start_idx].strip()
            headers = header_line.lstrip("@").lstrip("*").strip().split()
            
            # Get data lines for this block
            data_lines = []
            for line in lines[start_idx+1:next_idx]:
                line = line.strip()
                if line and not line.startswith("*") and not line.startswith("@"):
                    # Split the line and handle column count mismatch
                    values = line.split()
                    
                    # Handle mismatch between header columns and data values
                    if len(values) != len(headers):
                        logger.warning(f"Column count mismatch: {len(headers)} header columns, {len(values)} data values")
                        
                        if len(values) > len(headers):
                            # Too many values - trim extras
                            values = values[:len(headers)]
                        else:
                            # Too few values - pad with None
                            values.extend([None] * (len(headers) - len(values)))
                            
                    data_lines.append(values)
            
            if data_lines:
                try:
                    # Create DataFrame for this block
                    block_df = DataFrame(data_lines, columns=headers)
                    
                    # Try to extract treatment number from surrounding text
                    treatment_lines = [
                        line.strip() for line in lines[start_idx-5:start_idx] 
                        if "TREATMENT" in line.upper()
                    ]
                    
                    if treatment_lines:
                        try:
                            parts = treatment_lines[0].split()
                            trt_num = next((p for p in parts if p.isdigit()), None)
                            if trt_num:
                                block_df["TRT"] = trt_num
                                logger.info(f"Added treatment number {trt_num} to data block")
                        except Exception as e:
                            logger.warning(f"Could not extract treatment number: {e}")
                    
                    # Add to collection of data frames
                    data_frames.append(block_df)
                    logger.info(f"Added data block with {len(block_df)} rows and {len(block_df.columns)} columns")
                except Exception as e:
                    logger.error(f"Error creating DataFrame for block: {e}")
        
        # Combine all data frames
        if not data_frames:
            logger.warning("No valid data blocks found in FORAGE.OUT file")
            return None
            
        try:
            # Combine all data frames (try to align columns)
            combined_data = pd.concat(data_frames, ignore_index=True)
            
            # Drop columns that are completely empty
            combined_data = combined_data.loc[:, combined_data.notna().any()]
            
            # Standardize data types
            combined_data = standardize_dtypes(combined_data)
            
            # Ensure TRT column exists
            if "TRT" not in combined_data.columns:
                if "TRNO" in combined_data.columns:
                    combined_data["TRT"] = combined_data["TRNO"]
                elif "TR" in combined_data.columns:
                    combined_data["TRT"] = combined_data["TR"]
                else:
                    # Create default TRT column
                    combined_data["TRT"] = "1"
            
            # Convert numeric columns
            for col in combined_data.columns:
                if col not in ["TRT", "TRNO", "TR"]:
                    combined_data[col] = pd.to_numeric(combined_data[col], errors='ignore')
            
            # Create DATE column if YEAR and DOY exist
            if "YEAR" in combined_data.columns and "DOY" in combined_data.columns:
                combined_data["DATE"] = pd.to_datetime(
                    combined_data["YEAR"].astype(str) + 
                    combined_data["DOY"].astype(str).str.zfill(3),
                    format="%Y%j",
                    errors='coerce'
                )
            
            # Log final result
            logger.info(f"Successfully read FORAGE.OUT with {len(combined_data)} rows and {len(combined_data.columns)} columns")
            return combined_data
            
        except Exception as e:
            logger.error(f"Error combining data frames: {e}")
            return None

    except Exception as e:
        logger.error(f"Error reading FORAGE.OUT file: {e}")
        return None

def modify_read_file(file_path: str) -> Optional[DataFrame]:
    """Enhanced read_file function with specialized handling for different file types."""
    try:
        # Normalize the file path to ensure the correct format
        file_path = os.path.normpath(file_path)
        print(f"Attempting to open file: {file_path}")
        print(f"File exists check: {os.path.exists(file_path)}")
        
        if not os.path.exists(file_path):
            logger.error(f"File does not exist: {file_path}")
            return None
            
        # Detect file type by name
        file_name = os.path.basename(file_path).upper()
        
        # Special handling for different file types
        if file_name == "FORAGE.OUT":
            logger.info("Detected FORAGE.OUT file, using specialized reader")
            return read_forage_file(file_path)
        
        # For other file types, use the original processing logic
        return read_file(file_path)
        
    except Exception as e:
        logger.error(f"Error in modified read_file: {e}")
        return None
def prepare_treatment(selected_folder: str, selected_experiment: str) -> Optional[DataFrame]:
    """Prepare treatment data based on selected folder and experiment."""
    try:
        # Get crop details
        crop_details = get_crop_details()
        crop_info = next(
            (crop for crop in crop_details 
             if crop['name'].upper() == selected_folder.upper()),
            None
        )
        
        if not crop_info:
            logger.error(f"Could not find crop information for folder {selected_folder}")
            return None
            
        # Get directory and construct file path
        folder_path = crop_info['directory'].strip()
        if not folder_path:
            logger.error(f"No directory found for crop {selected_folder}")
            return None
            
        file_path = os.path.join(folder_path, selected_experiment)
        return read_treatments(file_path)
        
    except Exception as e:
        logger.error(f"Error preparing treatment: {str(e)}")
        return None

def read_treatments(file_path: str) -> Optional[DataFrame]:
    """Read and process treatment file."""
    try:
        if not os.path.exists(file_path):
            logger.error(f"Treatment file does not exist: {file_path}")
            return None
            
        with open(file_path, "r") as file:
            lines = file.readlines()
            
        # Find treatment section
        treatment_begins = next(
            (i for i, line in enumerate(lines) if line.startswith("*TREATMENT")),
            None
        )
        
        if treatment_begins is None:
            return None
            
        treatment_ends = next(
            (i for i, line in enumerate(lines) 
             if line.startswith("*") and i > treatment_begins),
            len(lines)
        )
        
        # Process treatment data
        treatment_data = lines[treatment_begins:treatment_ends]
        not_trash_lines = [line for line in treatment_data if line.startswith(" ")]
        
        return DataFrame({
            "TR": [line[:3].strip() for line in not_trash_lines],
            "TNAME": [line[9:36].strip() for line in not_trash_lines],
        })
        
    except Exception as e:
        logger.error(f"Error reading treatments: {str(e)}")
        return None

def prepare_out_files(selected_folder: str) -> List[str]:
    """List OUT files in the selected folder."""
    try:
        # Get crop details for directory
        crop_details = get_crop_details()
        crop_info = next(
            (crop for crop in crop_details 
             if crop['name'].upper() == selected_folder.upper()),
            None
        )
        
        if not crop_info:
            logger.error(f"Could not find crop information for folder {selected_folder}")
            return []
            
        # Use directory from crop_info
        folder_path = crop_info['directory'].strip()
        if not folder_path:
            logger.error(f"No directory found for crop {selected_folder}")
            return []
            
        logger.info(f"Looking for OUT files in: {folder_path}")
        out_files = [f for f in os.listdir(folder_path) if f.endswith(".OUT")]
        logger.info(f"Output files found: {out_files}")
        return out_files
        
    except Exception as e:
        logger.error(f"Error preparing OUT files: {str(e)}")
        return []

def read_file(file_path: str) -> Optional[DataFrame]:
    """Read and process DSSAT output file with optimized performance."""
    try:
        # Normalize the file path to ensure the correct format
        file_path = os.path.normpath(file_path)
        print(f"Attempting to open file: {file_path}")
        print(f"File exists check: {os.path.exists(file_path)}")
        
        if not os.path.exists(file_path):
            logger.error(f"File does not exist: {file_path}")
            return None

        # Read file with efficient encoding handling
        encodings = ['utf-8', 'latin-1']
        lines = None
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as file:
                    lines = file.readlines()
                break
            except UnicodeDecodeError:
                continue

        if not lines:
            logger.error(f"Could not read file with any encoding: {file_path}")
            return None

        # Process data more efficiently
        data_frames = []
        treatment_indices = [i for i, line in enumerate(lines) if line.strip().upper().startswith("TREATMENT")]

        if treatment_indices:
            # Multiple treatment format
            for idx, start_idx in enumerate(treatment_indices):
                next_idx = treatment_indices[idx + 1] if idx + 1 < len(treatment_indices) else len(lines)
                df = process_treatment_block(lines[start_idx:next_idx])
                if df is not None:
                    data_frames.append(df)
        else:
            # Single treatment format
            df = process_treatment_block(lines)
            if df is not None:
                data_frames.append(df)

        # Combine and process data efficiently
        if data_frames:
            combined_data = pd.concat(data_frames, ignore_index=True)
            combined_data = combined_data.loc[:, combined_data.notna().any()]
            combined_data = standardize_dtypes(combined_data)
            
            # Create DATE column if possible
            if "YEAR" in combined_data.columns and "DOY" in combined_data.columns:
                combined_data["DATE"] = pd.to_datetime(
                    combined_data["YEAR"].astype(str) + 
                    combined_data["DOY"].astype(str).str.zfill(3),
                    format="%Y%j",
                    errors='coerce'
                )
                
            return combined_data

        return None

    except Exception as e:
        logger.error(f"Error processing file {file_path}: {str(e)}")
        return None


def process_treatment_block(lines: List[str]) -> Optional[DataFrame]:
    """Helper function to process a treatment block of data."""
    try:
        header_index = next((i for i, line in enumerate(lines) if line.startswith("@")), None)
        if header_index is None:
            return None

        headers = lines[header_index].lstrip("@").strip().split()
        data_lines = []
        
        # Process each data line
        for line in lines[header_index + 1:]:
            if line.strip() and not line.startswith("*"):
                values = line.strip().split()
                # Handle column count mismatch
                if len(values) > len(headers):
                    # If there are more values than headers, truncate to match header count
                    values = values[:len(headers)]
                    logger.warning(f"Data row has more columns than header. Truncating to {len(headers)} columns.")
                elif len(values) < len(headers):
                    # If there are fewer values than headers, pad with None
                    values.extend([None] * (len(headers) - len(values)))
                    logger.warning(f"Data row has fewer columns than header. Padding to {len(headers)} columns.")
                data_lines.append(values)

        if not data_lines:
            return None

        df = DataFrame(data_lines, columns=headers)
        
        # Extract treatment number if present
        treatment_line = next((line for line in lines if line.strip().upper().startswith("TREATMENT")), None)
        if treatment_line:
            try:
                trt_num = treatment_line.split()[1]
                df["TRT"] = trt_num
            except IndexError:
                pass
        if 'CR' in df.columns:
            df = df.drop(columns=['CR'])

        return df

    except Exception as e:
        logger.error(f"Error processing treatment block: {str(e)}")
        return None

def read_observed_data(selected_folder: str, selected_experiment: str, x_var: str, y_vars: List[str]) -> Optional[DataFrame]:
    """Read observed data from .xxT file matching experiment name pattern."""
    try:
        base_name = selected_experiment.split(".")[0]
        
        # Get crop details
        crop_details = get_crop_details()
        crop_info = next(
            (crop for crop in crop_details 
             if crop['name'].upper() == selected_folder.upper()),
            None
        )
        
        if not crop_info:
            logger.error(f"Could not find crop code for folder {selected_folder}")
            return None
            
        # Use crop directory
        folder_path = crop_info['directory'].strip()
        logger.info(f"Checking for T file in folder: {folder_path}")
        
        # Look for T file
        t_file_pattern = os.path.join(folder_path, f"{base_name}.{crop_info['code']}T")
        matching_files = [f for f in glob.glob(t_file_pattern) 
                         if not f.upper().endswith(".OUT")]
        
        if not matching_files:
            logger.warning(f"No matching .{crop_info['code']}T files found for {base_name}")
            return None
            
        # Read and process T file
        t_file = matching_files[0]
        with open(t_file, "r") as file:
            content = file.readlines()
            
        # Find header and data
        header_idx = next(
            (i for i, line in enumerate(content) if line.strip().startswith("@")),
            None
        )
        
        if header_idx is None:
            logger.error(f"No header line found in {t_file}")
            return None
            
        headers = content[header_idx].strip().lstrip("@").split()
        headers = [h.upper() for h in headers]
        
        data_rows = [
            line.strip().split()
            for line in content[header_idx + 1:]
            if line.strip() and not line.startswith("*")
        ]
        
        if not data_rows:
            logger.error("No data rows found")
            return None
            
        # Create and process DataFrame
        df = DataFrame(data_rows, columns=headers)
        df = df.rename(columns={"TRNO": "TRT"})
        df = df.rename(columns={"TR": "TRT"})
        df = df.rename(columns={"TN": "TRT"})
        df = df.loc[:, df.notna().any()]
        df = standardize_dtypes(df)
        
        # Process DATE column
        if "DATE" in df.columns:
            df["DATE"] = df["DATE"].apply(lambda x: unified_date_convert(date_str=str(x)))
            df["DATE"] = df["DATE"].dt.strftime("%Y-%m-%d")
            df = df.dropna(subset=["DATE"])
            
        # Process treatment columns
        for col in ["TRNO", "TRT","TR", "TN"]:
            if col in df.columns:
                df[col] = df[col].astype(str)
                
        # Validate required variables
        required_vars = ["TRT"] + [var for var in y_vars if var in df.columns]
        missing_vars = [var for var in required_vars if var not in df.columns]
        
        if missing_vars:
            logger.warning(f"Missing required variables: {missing_vars}")
            return None
            
        return df
        
    except Exception as e:
        logger.error(f"Error reading observed data: {str(e)}")
        return None

def create_batch_file(input_data: dict, DSSAT_BASE: str) -> str:
    """Create DSSAT batch file for treatment execution."""
    try:
        # Validate input
        required_fields = ["folders", "executables", "experiment", "treatment"]
        missing_fields = [field for field in required_fields if not input_data.get(field)]
        if missing_fields:
            raise ValueError(f"Missing required input data: {', '.join(missing_fields)}")
            
        # Get crop directory
        crop_details = get_crop_details()
        crop_info = next(
            (crop for crop in crop_details 
             if crop['name'].upper() == input_data["folders"].upper()),
            None
        )
        
        if not crop_info:
            raise ValueError(f"Could not find crop information for {input_data['folders']}")
            
        # Process treatments
        treatments = input_data["treatment"]
        if isinstance(treatments, str):
            treatments = [treatments]
            
        # Setup paths
        base_path = os.path.normpath(DSSAT_BASE)
        folder_path = crop_info['directory'].strip()
        
        if not folder_path:
            raise ValueError(f"No directory found for crop {input_data['folders']}")
            
        folder_path = os.path.normpath(folder_path)
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder path does not exist: {folder_path}")
            
        # Create batch file content
        batch_file_lines = [
            f"$BATCH({crop_info['code']})",
            "!",
            f"! Directory    : {folder_path}",
            f"! Command Line : {os.path.join(base_path, input_data['executables'])} B BatchFile.v48",
            f"! Experiment   : {input_data['experiment']}",
            f"! ExpNo        : {len(treatments)}",
            "!",
            "@FILEX                                                                                        TRTNO     RP     SQ     OP     CO"
        ]
        
        # Add treatment lines
        for treatment in treatments:
            try:
                trt_num = int(treatment)
                full_path = os.path.normpath(os.path.join(folder_path, input_data["experiment"]))
                
                if not os.path.exists(full_path):
                    raise FileNotFoundError(f"Experiment file does not exist: {full_path}")
                    
                padded_path = f"{full_path:<90}"
                line = f"{padded_path}{trt_num:>9}      1      0      0      0"
                batch_file_lines.append(line)
                
            except ValueError as e:
                raise ValueError(f"Invalid treatment number: {treatment}")
                
        # Write batch file
        batch_file_path = os.path.join(folder_path, "BatchFile.v48")
        with open(batch_file_path, "w", newline="\n", encoding='utf-8') as f:
            f.write("\n".join(batch_file_lines))
            
        logger.info(f"Created batch file: {batch_file_path}")
        return batch_file_path
        
    except Exception as e:
        logger.error(f"Error creating batch file: {str(e)}")
        raise

def run_treatment(input_data: dict, DSSAT_BASE: str) -> str:
    """Run DSSAT treatment."""
    if not input_data.get("treatment"):
        raise ValueError("No treatments selected")
        
    try:
        # Get crop directory
        crop_details = get_crop_details()
        crop_info = next(
            (crop for crop in crop_details 
             if crop['name'].upper() == input_data["folders"].upper()),
            None
        )
        
        if not crop_info:
            raise ValueError(f"Could not find crop information for {input_data['folders']}")
            
        # Setup working directory
        work_dir = crop_info['directory'].strip()
        if not os.path.exists(work_dir):
            raise FileNotFoundError(f"Working directory does not exist: {work_dir}")
            
        # Change to working directory
        original_dir = os.getcwd()
        os.chdir(work_dir)
        logger.info(f"Working in directory: {work_dir}")
        
        try:
            # Verify executable and batch file
            exe_path = os.path.normpath(os.path.join(DSSAT_BASE, input_data["executables"]))
            if not os.path.exists(exe_path):
                raise FileNotFoundError(f"Executable not found: {exe_path}")
                
            if not os.path.exists("BatchFile.v48"):
                raise FileNotFoundError("BatchFile.v48 not found in working directory")
                
            # Run DSSAT
            cmd = f'"{exe_path}" B BatchFile.v48'
            logger.info(f"Executing: {cmd}")
            
            result = subprocess.run(
                cmd, 
                shell=True, 
                capture_output=True, 
                text=True,
                encoding='utf-8'
            )
            
            # Handle execution results
            if result.returncode == 99:
                error_msg = (
                    "DSSAT simulation failed. Please verify:\n"
                    "1. Input files are properly formatted\n"
                    "2. All required weather files are present\n"
                    "3. Cultivation and treatment parameters are valid"
                )
                raise RuntimeError(error_msg)
            elif result.returncode != 0:
                error_msg = result.stderr or f"Unknown error (code {result.returncode})"
                raise RuntimeError(f"DSSAT execution failed: {error_msg}")
                
            return result.stdout
            
        finally:
            os.chdir(original_dir)
            logger.info("Restored original directory")
            
    except Exception as e:
        logger.error(f"Error in run_treatment: {str(e)}")
        raise

def read_evaluate_file(selected_folder: str) -> Optional[DataFrame]:
    """Read and process EVALUATE.OUT file."""
    try:
        # Get crop details
        crop_details = get_crop_details()
        crop_info = next(
            (crop for crop in crop_details 
              if crop['name'].upper() == selected_folder.upper()),
            None
        )
        
        if not crop_info:
            logger.error(f"Could not find crop information for folder {selected_folder}")
            return None
            
        # Construct file path
        folder_path = crop_info['directory'].strip()
        evaluate_path = os.path.join(folder_path, "EVALUATE.OUT")
        
        if not os.path.exists(evaluate_path):
            logger.warning(f"EVALUATE.OUT not found in {folder_path}")
            return None
            
        # Read file
        try:
            with open(evaluate_path, 'r', encoding='utf-8') as file:
                lines = file.readlines()
        except UnicodeDecodeError:
            with open(evaluate_path, 'r', encoding='latin-1') as file:
                lines = file.readlines()
                
        # Find header
        header_idx = next(
            (i for i, line in enumerate(lines) 
              if line.strip().startswith("@")),
            None
        )
        
        if header_idx is None:
            logger.error(f"No header found in {evaluate_path}")
            return None
            
        # Process data
        headers = lines[header_idx].strip().lstrip("@").split()
        logger.info(f"Found headers: {headers}")
        
        data_lines = [
            line.strip().split()
            for line in lines[header_idx + 1:]
            if line.strip() and not line.startswith("*")
        ]
        
        if not data_lines:
            logger.warning(f"No data found in {evaluate_path}")
            return None
            
        # Create DataFrame
        df = DataFrame(data_lines, columns=headers)
        logger.info(f"Initial DataFrame columns: {df.columns.tolist()}")
        
        # Convert string columns to numeric where possible
        for col in df.columns:
            df[col] = to_numeric(df[col], errors='coerce')
        
        # Handle missing values - replace with NaN
        for val in config.MISSING_VALUES:
            df = df.replace(val, nan)
        
        # Standardize treatment column names with case-insensitive check
        treatment_cols = ['TRNO', 'TR', 'TRT','TN']
        found_trt_col = None
        for col in df.columns:
            if col.upper() in [t.upper() for t in treatment_cols]:
                found_trt_col = col
                if col != 'TRNO':
                    df = df.rename(columns={col: 'TRNO'})
                    logger.info(f"Renamed '{col}' column to 'TRNO'")
                break
                
        if found_trt_col is None:
            logger.warning("No treatment column (TRNO/TR/TRT) found in the data")
            # Create a default TRNO column if none exists
            df['TRNO'] = 1
            logger.info("Created default TRNO column with value 1")
            
        # Log final columns for debugging
        logger.info(f"Final DataFrame columns: {df.columns.tolist()}")
        
        df = standardize_dtypes(df)
        return df
        
    except Exception as e:
        logger.error(f"Error reading EVALUATE.OUT: {str(e)}")
        logger.exception("Detailed error:")
        return None