import os
import shutil
import re
import logging
from pathlib import Path
from datetime import datetime
from django.conf import settings
from .utils.db_queries import fetch_customer_data, fetch_product_details, fetch_kit_elements, get_db_connection
import ibm_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
SOURCE_DIR = r"E:\Onedrive_it_intern\OneDrive - SKAPS INDUSTRIES INDIA PVT.LTD\Jay Vyas's files - Images from Server\Results From Bot"
DESTINATION_BASE = r"\\192.168.4.32\testKit"


def get_element_data_from_db(element_desc):
    """
    Get complete data for an element from SKP_KITUPLOAD table
    
    Args:
        element_desc: Element description (filename without extension)
    
    Returns:
        dict: All data from SKP_KITUPLOAD for this element, or None if not found
    """
    try:
        conn = get_db_connection()
        if conn is None:
            logger.error("Could not connect to database")
            return None
        
        try:
            # Query SKP_KITUPLOAD table for this element
            sql = """
                SELECT 
                    BOXNUMBER,
                    PALLETNUMBER,
                    PACKINGSEQUENCE,
                    ELEMENTDESC,
                    ITEMTYPECODE,
                    DECOSUBCODE01,
                    DECOSUBCODE02,
                    DECOSUBCODE03,
                    DECOSUBCODE04,
                    DECOSUBCODE05,
                    DECOSUBCODE06,
                    DECOSUBCODE07,
                    DECOSUBCODE08,
                    DECOSUBCODE09,
                    DECOSUBCODE10
                FROM SKP_KITUPLOAD 
                WHERE UPPER(ELEMENTDESC) = UPPER(?)
            """
            
            stmt = ibm_db.prepare(conn, sql)
            ibm_db.bind_param(stmt, 1, element_desc)
            ibm_db.execute(stmt)
            
            data = ibm_db.fetch_assoc(stmt)
            
            if not data:
                logger.info(f"Element not found in SKP_KITUPLOAD: {element_desc}")
                return None
            
            logger.info(f"Found element in SKP_KITUPLOAD: {element_desc}")
            
            # Return all data
            return {
                'ELEMENTDESC': data.get('ELEMENTDESC', '').strip(),
                'BOXNUMBER': str(data.get('BOXNUMBER', '1')).strip() or '1',
                'PALLETNUMBER': str(data.get('PALLETNUMBER', '1')).strip() or '1',
                'PACKINGSEQUENCE': data.get('PACKINGSEQUENCE', '').strip(),
                'ITEMTYPECODE': data.get('ITEMTYPECODE', '').strip(),
                'DECOSUBCODE01': data.get('DECOSUBCODE01', '').strip(),
                'DECOSUBCODE02': data.get('DECOSUBCODE02', '').strip(),
                'DECOSUBCODE03': data.get('DECOSUBCODE03', '').strip(),
                'DECOSUBCODE04': data.get('DECOSUBCODE04', '').strip(),
                'DECOSUBCODE05': data.get('DECOSUBCODE05', '').strip(),
                'DECOSUBCODE06': data.get('DECOSUBCODE06', '').strip(),
                'DECOSUBCODE07': data.get('DECOSUBCODE07', '').strip(),
                'DECOSUBCODE08': data.get('DECOSUBCODE08', '').strip(),
                'DECOSUBCODE09': data.get('DECOSUBCODE09', '').strip(),
                'DECOSUBCODE10': data.get('DECOSUBCODE10', '').strip()
            }
            
        except Exception as e:
            logger.error(f"Error querying database for {element_desc}: {str(e)}")
            return None
        finally:
            if conn:
                try:
                    ibm_db.close(conn)
                except:
                    pass
                    
    except Exception as e:
        logger.error(f"Error in get_element_data_from_db for {element_desc}: {str(e)}")
        return None


def get_customer_data_for_element(element_data):
    """
    Get customer data for an element using existing fetch functions.
    Since we don't have order/demand directly in SKP_KITUPLOAD,
    we need to get them from other tables.
    """
    try:
        # Get values from element data
        item_type = element_data.get('ITEMTYPECODE', '').strip()
        deco01 = element_data.get('DECOSUBCODE01', '').strip()
        deco02 = element_data.get('DECOSUBCODE02', '').strip()
        deco03 = element_data.get('DECOSUBCODE03', '').strip()
        
        # Try to find order and demand from other tables
        # Since we don't have the exact table structure, we'll use the subcodes
        # as a fallback. In many systems, DECOSUBCODE01 is the order code
        # and DECOSUBCODE02 is the demand code.
        
        order_code = deco01 if deco01 else 'UNKNOWN'
        demand_code = deco02 if deco02 else 'UNKNOWN'
        
        # If we have both codes, try to fetch customer data
        if order_code != 'UNKNOWN' and demand_code != 'UNKNOWN':
            try:
                customer_data = fetch_customer_data(order_code, demand_code)
                if customer_data:
                    return customer_data
            except Exception as e:
                logger.warning(f"Could not fetch customer data: {e}")
        
        # Try with just the order code if demand is missing
        if order_code != 'UNKNOWN' and demand_code == 'UNKNOWN':
            # Try to find any demand for this order
            try:
                # This is a simplified query - you need to know your table structure
                conn = get_db_connection()
                if conn:
                    sql = """
                        SELECT DISTINCT PRODUCTIONDEMANDCODE 
                        FROM SOME_ORDER_TABLE 
                        WHERE PRODUCTIONORDERCODE = ?
                        LIMIT 1
                    """
                    # Replace with actual table name
                    stmt = ibm_db.prepare(conn, sql)
                    ibm_db.bind_param(stmt, 1, order_code)
                    ibm_db.execute(stmt)
                    result = ibm_db.fetch_assoc(stmt)
                    if result:
                        demand_code = result.get('PRODUCTIONDEMANDCODE', '').strip()
                    ibm_db.close(conn)
            except:
                pass
        
        # Return default customer data with the codes we found
        return {
            'CustomerName': 'UNKNOWN',
            'CustomerPO': 'NONE',
            'CustomerCode': 'UNKNOWN',
            'OrderCode': order_code,
            'DemandCode': demand_code
        }
        
    except Exception as e:
        logger.error(f"Error getting customer data: {str(e)}")
        return {
            'CustomerName': 'UNKNOWN',
            'CustomerPO': 'NONE',
            'CustomerCode': 'UNKNOWN'
        }


def extract_pressur_bal_and_pl1_from_data(element_data):
    """
    Extract PressurBal and PL1 from element data
    """
    pressur_bal = None
    pl1 = None
    packing_sequence = element_data.get('PACKINGSEQUENCE', '').strip()
    
    # Extract PL1 from PACKINGSEQUENCE
    if packing_sequence and packing_sequence != 'N/A':
        match = re.search(r'PL(\d+)', packing_sequence.upper())
        if match:
            pl1 = match.group(1)
        elif 'PL' in packing_sequence.upper():
            pl1 = '1'
    
    # If not found, try from subcodes
    if pl1 is None:
        for i in range(1, 11):
            subcode_key = f'DECOSUBCODE{str(i).zfill(2)}'
            subcode_value = element_data.get(subcode_key, '').strip()
            if subcode_value and subcode_value != 'N/A':
                if 'PL1' in subcode_value.upper():
                    match = re.search(r'PL1\s*(\d+)?', subcode_value.upper())
                    pl1 = match.group(1) if match and match.group(1) else '1'
                    break
                elif 'PL' in subcode_value.upper():
                    match = re.search(r'PL\s*(\d+)', subcode_value.upper())
                    pl1 = match.group(1) if match else '1'
                    break
    
    # Extract pressur_bal from DECOSUBCODE03
    subcode03 = element_data.get('DECOSUBCODE03', '').strip()
    if subcode03 and subcode03 != 'N/A':
        if 'PRESSURBAL' in subcode03.upper():
            match = re.search(r'PRESSURBAL\s*(\d+)', subcode03.upper())
            pressur_bal = match.group(1) if match else subcode03
        else:
            pressur_bal = subcode03
    
    # Defaults
    if pressur_bal is None:
        pressur_bal = '1'
    if pl1 is None:
        pl1 = '1'
    if not packing_sequence:
        packing_sequence = pl1
    
    return pressur_bal, pl1, packing_sequence


def build_folder_path_for_element(element_desc, element_data):
    """
    Build folder path for an element using the same logic as build_image_url
    """
    try:
        if not element_data:
            return None, False, "No element data provided"
        
        # Get customer data (this will also get order/demand codes)
        customer_data = get_customer_data_for_element(element_data)
        
        # Get order and demand codes from customer data
        order_code = customer_data.get('OrderCode', '').strip()
        demand_code = customer_data.get('DemandCode', '').strip()
        
        # If order/demand not found, use subcodes as fallback
        if not order_code:
            order_code = element_data.get('DECOSUBCODE01', '').strip()
        if not demand_code:
            demand_code = element_data.get('DECOSUBCODE02', '').strip()
        
        # If still not found, use default
        if not order_code:
            order_code = 'UNKNOWN_ORDER'
        if not demand_code:
            demand_code = 'UNKNOWN_DEMAND'
        
        # Get customer name and PO
        customer_name = customer_data.get('CustomerName', 'UNKNOWN').strip()
        customer_po = customer_data.get('CustomerPO', 'NONE').strip()
        
        if not customer_po or customer_po == '-':
            customer_po = 'NONE'
        
        # Clean values (same as build_image_url)
        customer_clean = re.sub(r'[^\w\s-]', '', customer_name).strip().upper()
        customer_slug = customer_clean.replace(' ', '-').replace('--', '-')
        po_clean = customer_po.upper()
        order_clean = order_code.strip().upper()
        demand_clean = demand_code.strip().upper()
        
        # Extract values
        pressur_bal, pl1, packing_sequence = extract_pressur_bal_and_pl1_from_data(element_data)
        
        subcode03 = element_data.get('DECOSUBCODE03', '').strip()
        pallet_number = element_data.get('PALLETNUMBER', '1').strip()
        box_number = element_data.get('BOXNUMBER', '1').strip()
        
        # Clean values for folder names
        pressur_bal_clean = re.sub(r'\D', '', str(pressur_bal)) or '1'
        
        # Use packing_sequence for box folder
        if packing_sequence and packing_sequence != 'N/A':
            box_folder_value = re.sub(r'[^\w\-]', '', packing_sequence).strip()
            if not box_folder_value:
                box_folder_value = pl1
        else:
            box_folder_value = pl1
        
        pallet_clean = str(pallet_number).strip().upper()
        box_clean = str(box_number).strip().upper()
        
        # Build folder structure (same as build_image_url)
        demand_folder = f"{demand_clean}_{subcode03}" if subcode03 else demand_clean
        folder_path = f"{customer_slug}--{po_clean}/{order_clean}/{demand_folder}/PALLET_{pallet_clean}_{subcode03}/BOX_{box_clean}_{box_folder_value}"
        
        logger.info(f"Generated folder path: {folder_path}")
        return folder_path, True, "Folder path built successfully"
        
    except Exception as e:
        logger.error(f"Error building folder path: {str(e)}")
        return None, False, f"Error: {str(e)}"



def move_txt_files():
    """
    Main function to move text files from source to destination
    """
    source_path = Path(SOURCE_DIR)
    dest_base = Path(DESTINATION_BASE)
    
    # Validate directories
    if not source_path.exists():
        logger.error(f"Source directory not found: {SOURCE_DIR}")
        return False
    
    if not dest_base.exists():
        logger.error(f"Destination base directory not found: {DESTINATION_BASE}")
        # Try to create it
        try:
            dest_base.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created destination directory: {DESTINATION_BASE}")
        except Exception as e:
            logger.error(f"Could not create destination directory: {e}")
            return False
    
    # Find all .txt files
    txt_files = list(source_path.glob('*.txt'))
    
    if not txt_files:
        logger.info("No .txt files found in source directory")
        return True
    
    logger.info(f"Found {len(txt_files)} .txt files to process")
    
    moved_count = 0
    failed_count = 0
    skipped_count = 0
    
    for file_path in txt_files:
        file_name = file_path.stem  # Get filename without extension
        
        logger.info(f"Processing: {file_name}")
        
        try:
            # Step 1: Check if element exists in SKP_KITUPLOAD
            element_data = get_element_data_from_db(file_name)
            
            if not element_data:
                logger.info(f"Element '{file_name}' not found in database. Skipping.")
                skipped_count += 1
                continue
            
            logger.info(f"Found data for {file_name}:")
            logger.info(f"  PALLETNUMBER: {element_data.get('PALLETNUMBER')}")
            logger.info(f"  BOXNUMBER: {element_data.get('BOXNUMBER')}")
            logger.info(f"  PACKINGSEQUENCE: {element_data.get('PACKINGSEQUENCE')}")
            logger.info(f"  DECOSUBCODE01: {element_data.get('DECOSUBCODE01')}")
            logger.info(f"  DECOSUBCODE02: {element_data.get('DECOSUBCODE02')}")
            logger.info(f"  DECOSUBCODE03: {element_data.get('DECOSUBCODE03')}")
            
            # Step 2: Build folder path
            folder_path, success, message = build_folder_path_for_element(file_name, element_data)
            
            if not success:
                logger.warning(f"Could not build folder path for {file_name}: {message}")
                skipped_count += 1
                continue
            
            # Step 3: Full destination path
            dest_folder = dest_base / folder_path
            dest_file_path = dest_folder / file_path.name
            
            # Step 4: Create destination folder
            try:
                dest_folder.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created/Verified folder: {dest_folder}")
            except Exception as e:
                logger.error(f"Could not create destination folder: {e}")
                failed_count += 1
                continue
            
            # Step 5: Handle duplicate files
            if dest_file_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_name = f"{file_path.stem}.txt"
                dest_file_path = dest_folder / new_name
                logger.info(f"File exists, renaming to: {new_name}")
            
            # Step 6: Move the file
            try:
                shutil.move(str(file_path), str(dest_file_path))
                moved_count += 1
                logger.info(f"✓ Moved: {file_path.name} -> {dest_folder.relative_to(dest_base)}")
            except Exception as e:
                logger.error(f"Error moving file: {e}")
                failed_count += 1
            
        except Exception as e:
            logger.error(f"Error processing {file_path.name}: {str(e)}")
            import traceback
            traceback.print_exc()
            failed_count += 1
    
    # Summary
    logger.info("=" * 60)
    logger.info(f"✅ Successfully moved: {moved_count} files")
    logger.info(f"⏭️ Skipped (not in DB): {skipped_count} files")
    logger.info(f"❌ Failed: {failed_count} files")
    logger.info("=" * 60)
    
    return moved_count > 0


# Django view to trigger file move
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET


@csrf_exempt
@require_POST
def move_txt_files_endpoint(request):
    """
    Django endpoint to trigger moving text files
    """
    try:
        # Get optional parameters
        specific_file = request.POST.get('file_name', '').strip()
        
        if specific_file:
            # Process only specific file
            source_path = Path(SOURCE_DIR) / f"{specific_file}.txt"
            
            if not source_path.exists():
                return JsonResponse({
                    'status': 'error',
                    'message': f'File not found: {specific_file}.txt'
                }, status=404)
            
            # Check if element exists in database
            element_data = get_element_data_from_db(specific_file)
            
            if not element_data:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Element not found in database: {specific_file}'
                }, status=404)
            
            # Build folder path
            folder_path, success, message = build_folder_path_for_element(specific_file, element_data)
            
            if not success:
                return JsonResponse({
                    'status': 'error',
                    'message': message
                }, status=400)
            
            # Move the file
            dest_base = Path(DESTINATION_BASE)
            dest_folder = dest_base / folder_path
            dest_file_path = dest_folder / f"{specific_file}.txt"
            
            dest_folder.mkdir(parents=True, exist_ok=True)
            
            if dest_file_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_name = f"{specific_file}_{timestamp}.txt"
                dest_file_path = dest_folder / new_name
            
            shutil.move(str(source_path), str(dest_file_path))
            
            return JsonResponse({
                'status': 'success',
                'message': f'File moved successfully',
                'source': str(source_path),
                'destination': str(dest_file_path),
                'folder': str(folder_path)
            })
        else:
            # Move all files
            success = move_txt_files()
            return JsonResponse({
                'status': 'success' if success else 'error',
                'message': 'File move operation completed'
            })
            
    except Exception as e:
        logger.error(f"Error in move_txt_files_endpoint: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f"Server error: {str(e)}"
        }, status=500)


@csrf_exempt
@require_GET
def test_element_lookup(request):
    """
    Test endpoint to check if an element exists in database
    """
    try:
        element_desc = request.GET.get('element_desc', '').strip()
        
        if not element_desc:
            return JsonResponse({
                'status': 'error',
                'message': 'element_desc parameter required'
            }, status=400)
        
        # Check if element exists in database
        element_data = get_element_data_from_db(element_desc)
        
        if element_data:
            return JsonResponse({
                'status': 'success',
                'found': True,
                'data': element_data
            })
        else:
            return JsonResponse({
                'status': 'success',
                'found': False,
                'message': f'Element not found: {element_desc}'
            })
            
    except Exception as e:
        logger.error(f"Error in test_element_lookup: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f"Server error: {str(e)}"
        }, status=500)





# @require_POST
# @csrf_protect
# def upload_box_capture(request):

#     try:

#         # --------------------------------------------------
#         # Get image
#         # ---------------------------------------------------

#         image_data = request.POST.get("box_image")

#         if not image_data:

#             return JsonResponse({
#                 "status": "error",
#                 "message": "No image received."
#             })


#         # --------------------------------------------------
#         # Get order information
#         # --------------------------------------------------

#         production_order_code = (
#             request.POST.get(
#                 "production_order_code",
#                 "UNKNOWN_ORDER"
#             )
#         )

#         production_demand_code = (
#             request.POST.get(
#                 "production_demand_code",
#                 "UNKNOWN_DEMAND"
#             )
#         )

#         pallet_number = (
#             request.POST.get(
#                 "pallet_number",
#                 "UNKNOWN_PALLET"
#             )
#         )

#         box_number = (
#             request.POST.get(
#                 "box_number",
#                 "UNKNOWN_BOX"
#             )
#         )


#         # --------------------------------------------------
#         # Create folder if it doesn't exist
#         # --------------------------------------------------

#         os.makedirs(
#             BOX_IMAGE_PATH,
#             exist_ok=True
#         )


#         # --------------------------------------------------
#         # Remove base64 prefix if present
#         # --------------------------------------------------

#         if "," in image_data:

#             image_data = image_data.split(
#                 ",",
#                 1
#             )[1]


#         # --------------------------------------------------
#         # Decode image
#         # --------------------------------------------------

#         image_bytes = base64.b64decode(
#             image_data
#         )


#         # --------------------------------------------------
#         # Create filename
#         # --------------------------------------------------

#         timestamp = datetime.now().strftime(
#             "%Y%m%d_%H%M%S_%f"
#         )


#         filename = (
#             f"{production_order_code}_"
#             f"{production_demand_code}_"
#             f"Pallet_{pallet_number}_"
#             f"Box_{box_number}_"
#             f"{timestamp}.jpg"
#         )


#         # Remove invalid Windows filename characters
#         invalid_chars = '<>:"/\\|?*'


#         for char in invalid_chars:

#             filename = filename.replace(
#                 char,
#                 "_"
#             )


#         # --------------------------------------------------
#         # Full path
#         # --------------------------------------------------

#         file_path = os.path.join(
#             BOX_IMAGE_PATH,
#             filename
#         )


#         # --------------------------------------------------
#         # Save image
#         # --------------------------------------------------

#         with open(
#             file_path,
#             "wb"
#         ) as image_file:

#             image_file.write(
#                 image_bytes
#             )


#         print(
#             "✅ Box image saved:",
#             file_path
#         )


#         # --------------------------------------------------
#         # Response
#         # --------------------------------------------------

#         return JsonResponse({

#             "status": "success",

#             "message":
#                 "Box image uploaded successfully.",

#             "filepath":
#                 file_path,

#             "filename":
#                 filename
#         })


#     except Exception as e:

#         print(
#             "❌ Box image upload error:",
#             str(e)
#         )


#         return JsonResponse({

#             "status": "error",

#             "message":
#                 str(e)

#         }, status=500)


