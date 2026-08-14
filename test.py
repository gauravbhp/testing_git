import os
import base64
import re
import time
import datetime
from django.conf import settings
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils.text import slugify
from .utils.db_queries import fetch_customer_data, fetch_product_details, fetch_kit_elements
import ibm_db
from .utils.db_queries import get_db_connection

# ---------------------- HELPER: LOG TIME INFORMATION ----------------------
def log_time_info(log_type, start_time, end_time, element_desc, production_order_code, production_demand_code, 
                  customer_data, folder_structure, pallet_number, box_number, is_human_image=False, status="success"):
    """
    Log time information to a text file
    
    Args:
        log_type: 'capture_to_upload' or 'upload_duration'
        start_time: Start time (datetime object or timestamp)
        end_time: End time (datetime object or timestamp)
        element_desc: Element description
        production_order_code: Production order code
        production_demand_code: Production demand code
        customer_data: Customer data dictionary
        folder_structure: Folder structure path
        pallet_number: Pallet number
        box_number: Box number
        is_human_image: Boolean indicating if it's human image
        status: Status of operation ('success', 'failed', 'cancelled')
    """
    
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(settings.BASE_DIR, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    # Log filename based on date
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    log_filename = f"image_upload_times_{today}.txt"
    log_filepath = os.path.join(logs_dir, log_filename)
    
    # Calculate duration
    if isinstance(start_time, (int, float)):
        # If timestamp
        duration = end_time - start_time if isinstance(end_time, (int, float)) else None
        start_datetime = datetime.datetime.fromtimestamp(start_time)
        end_datetime = datetime.datetime.fromtimestamp(end_time)
    else:
        # If datetime objects
        duration = (end_time - start_time).total_seconds() if end_time and start_time else None
        start_datetime = start_time
        end_datetime = end_time
    
    # Get clean values for logging
    customer_name = customer_data.get('CustomerName', 'UNKNOWN').strip() if customer_data else 'UNKNOWN'
    customer_po = customer_data.get('CustomerPO', 'NONE').strip() if customer_data else 'NONE'
    
    # Clean values
    customer_name_clean = re.sub(r'[^\w\s-]', '', customer_name).strip().upper()
    customer_po_clean = customer_po.upper()
    order_clean = production_order_code.strip().upper()
    demand_clean = production_demand_code.strip().upper()
    pallet_clean = str(pallet_number).strip().upper()
    box_clean = str(box_number).strip().upper()
    
    # Extract PL value from folder structure or use default
    pl_match = re.search(r'BOX_\d+_(\d+)', folder_structure) if folder_structure else None
    pl_clean = pl_match.group(1) if pl_match else '1'
    
    # Create log entry
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    image_type = "Human Image" if is_human_image else "Element Image"
    
    log_entry = f"""
{'='*80}
[{timestamp}] {log_type.upper()} - {image_type}
{'='*80}

Image Details:
-------------
Element Description: {element_desc}
Image Type: {image_type}
Status: {status.upper()}

Order Information:
----------------
Order Code: {order_clean}
Demand Code: {demand_clean}

Customer Information:
====================
Customer: {customer_name_clean}
PO: {customer_po_clean}

Container Information:
=====================
Pallet: {pallet_clean}
Box: {box_clean}
PL: {pl_clean}

Time Information:
===============
Start Time (Capture): {start_datetime.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if start_datetime else 'N/A'}
End Time (Upload): {end_datetime.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if end_datetime else 'N/A'}
Total Duration: {duration:.3f} seconds ({duration/60:.2f} minutes) if duration else 'N/A'

System Information:
==================
Folder Path: {folder_structure}
Log Created: {timestamp}

{'='*80}

"""
    
    # Write to log file
    try:
        with open(log_filepath, 'a', encoding='utf-8') as log_file:
            log_file.write(log_entry)
        print(f"[TIME LOG] Successfully logged to: {log_filepath}")
        return True
    except Exception as e:
        print(f"[TIME LOG ERROR] Failed to write log: {e}")
        return False
 
def log_time_to_text_file(log_data):
    """
    Save time tracking information to a text file
    
    Args:
        log_data: Dictionary containing all timing information
    """
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(settings.BASE_DIR, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    # Create filename with date
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    log_filename = f"capture_upload_times_{today}.txt"
    log_filepath = os.path.join(logs_dir, log_filename)
    
    # Format the log entry
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    log_entry = f"""
{'='*80}
LOG ENTRY: {timestamp}
{'='*80}

IMAGE DETAILS:
--------------
Element Description: {log_data.get('element_desc', 'N/A')}
Image Type: {log_data.get('image_type', 'N/A')}
Status: {log_data.get('status', 'N/A')}

ORDER INFORMATION:
-----------------
Order Code: {log_data.get('order_code', 'N/A')}
Demand Code: {log_data.get('demand_code', 'N/A')}

CUSTOMER INFORMATION:
====================
Customer: {log_data.get('customer_name', 'N/A')}
PO: {log_data.get('customer_po', 'N/A')}

CONTAINER INFORMATION:
=====================
Pallet: {log_data.get('pallet_number', 'N/A')}
Box: {log_data.get('box_number', 'N/A')}
PL: {log_data.get('pl_value', 'N/A')}

TIME INFORMATION:
================
Capture Start Time: {log_data.get('capture_start_time', 'N/A')}
Back Image Capture Time: {log_data.get('back_capture_time', 'N/A')}
Front Image Capture Time: {log_data.get('front_capture_time', 'N/A')}
Upload Start Time: {log_data.get('upload_start_time', 'N/A')}
Upload Complete Time: {log_data.get('upload_complete_time', 'N/A')}

DURATIONS:
----------
Total Duration (Capture to Upload): {log_data.get('total_duration', 'N/A')} seconds
Back Capture Duration: {log_data.get('back_capture_duration', 'N/A')} seconds
Front Capture Duration: {log_data.get('front_capture_duration', 'N/A')} seconds
Between Captures Duration: {log_data.get('between_captures_duration', 'N/A')} seconds
Upload Processing Duration: {log_data.get('upload_duration', 'N/A')} seconds

SYSTEM INFORMATION:
==================
Folder Path: {log_data.get('folder_path', 'N/A')}
IP Address: {log_data.get('ip_address', 'N/A')}
User Agent: {log_data.get('user_agent', 'N/A')}

{'='*80}

"""
    
    # Write to log file
    try:
        with open(log_filepath, 'a', encoding='utf-8') as log_file:
            log_file.write(log_entry)
        print(f"[TIME LOG] Successfully saved to: {log_filepath}")
        return True
    except Exception as e:
        print(f"[TIME LOG ERROR] Failed to write log: {e}")
        return False 
 

# ---------------------- TEST LOGGING ENDPOINT ----------------------
@csrf_exempt
def test_logging(request):
    """Test endpoint to verify logging is working"""
    if request.method == 'GET':
        try:
            test_log = log_capture_time_simple(
                element_desc="TEST_IMAGE",
                order_code="TEST_ORDER",
                demand_code="TEST_DEMAND",
                pallet_number="1",
                box_number="1",
                capture_start=datetime.datetime.now().isoformat(),
                upload_complete=datetime.datetime.now().isoformat(),
                status="test",
                extra_data="This is a test log entry"
            )
            
            if test_log:
                return JsonResponse({'status': 'success', 'message': 'Test log created successfully'})
            else:
                return JsonResponse({'status': 'error', 'message': 'Failed to create log'}, status=500)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Use GET request'}, status=405)

import json    
    
@csrf_exempt
def save_timing_log_endpoint(request):
    """Simple endpoint to save timing log from frontend"""
    if request.method == 'POST':
        try:
            # Try to get JSON data
            try:
                data = json.loads(request.body)
            except:
                data = request.POST.dict()
            
            # Extract data
            element_desc = data.get('element_desc', 'Unknown')
            order_code = data.get('order_code', '')
            demand_code = data.get('demand_code', '')
            pallet_number = data.get('pallet_number', '')
            box_number = data.get('box_number', '')
            capture_start = data.get('capture_start_time', '')
            upload_complete = data.get('upload_complete_time', datetime.datetime.now().isoformat())
            status = data.get('status', 'completed')
            
            # Log to text file
            log_capture_time_simple(
                element_desc=element_desc,
                order_code=order_code,
                demand_code=demand_code,
                pallet_number=pallet_number,
                box_number=box_number,
                capture_start=capture_start,
                upload_complete=upload_complete,
                status=status,
                extra_data=data.get('extra_data', '')
            )
            
            return JsonResponse({'status': 'success', 'message': 'Log saved'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)
    



# ---------------------- HELPER: EXTRACT PRESSURBAL AND PL1 ----------------------
def extract_pressur_bal_and_pl1(product_details, kit_elements=None):
    """
    Extract PressurBal and PL1 values from subcodes or kit elements
    
    Args:
        product_details: Dictionary with Subcode01-10 values
        kit_elements: List of kit element dictionaries from fetch_kit_elements()
    
    Returns:
        tuple: (pressur_bal, pl1, packing_sequence)
    """
    pressur_bal = None
    pl1 = None
    packing_sequence = None
    
    print("\n[EXTRACT] Starting extraction...")
    
    # ========== EXTRACT PL1 AND PACKINGSEQUENCE FROM KIT ELEMENTS ==========
    if kit_elements and len(kit_elements) > 0:
        print(f"[EXTRACT] Checking {len(kit_elements)} kit elements...")
        for kit in kit_elements:
            # Get PACKINGSEQUENCE value
            packing_sequence = kit.get('PACKINGSEQUENCE', '').strip()
            if packing_sequence and packing_sequence != 'N/A':
                print(f"[EXTRACT] Found PACKINGSEQUENCE: '{packing_sequence}'")
                
                # Check for PL1, PL2, PL3, etc.
                match = re.search(r'PL(\d+)', packing_sequence.upper())
                if match:
                    pl1 = match.group(1)
                    print(f"[EXTRACT] PL1 extracted from PACKINGSEQUENCE: {pl1}")
                    break
                elif 'PL' in packing_sequence.upper():
                    pl1 = '1'
                    print(f"[EXTRACT] PL found (no number) from PACKINGSEQUENCE, default: {pl1}")
                    break
                else:
                    # If no PL found, use the entire packing_sequence as box identifier
                    print(f"[EXTRACT] Using PACKINGSEQUENCE as box identifier: {packing_sequence}")
                    break
    
    # ========== EXTRACT PL1 FROM PRODUCT DETAILS (Fallback) ==========
    if pl1 is None and product_details:
        print("[EXTRACT] PL1 not in kit elements, checking product details...")
        
        # Check all Subcode fields
        for i in range(1, 11):
            subcode_key = f'Subcode{str(i).zfill(2)}'
            subcode_value = product_details.get(subcode_key, '').strip()
            
            if subcode_value and subcode_value != 'N/A':
                print(f"[EXTRACT] Checking {subcode_key}: '{subcode_value}'")
                
                # Check for PL pattern
                if 'PL1' in subcode_value.upper():
                    match = re.search(r'PL1\s*(\d+)?', subcode_value.upper())
                    if match and match.group(1):
                        pl1 = match.group(1)
                    else:
                        pl1 = '1'
                    print(f"[EXTRACT] PL1 found in {subcode_key}: {pl1}")
                    break
                elif 'PL' in subcode_value.upper():
                    match = re.search(r'PL\s*(\d+)', subcode_value.upper())
                    if match:
                        pl1 = match.group(1)
                        print(f"[EXTRACT] PL found in {subcode_key}: {pl1}")
                        break
                # Check for plain digits <= 3 (legacy support)
                elif subcode_value.isdigit() and len(subcode_value) <= 3:
                    if pl1 is None:
                        pl1 = subcode_value
                        print(f"[EXTRACT] Numeric PL1 from {subcode_key}: {pl1}")
    
    # ========== EXTRACT PRESSURBAL FROM PRODUCT DETAILS ==========
    if product_details:
        # Check Subcode03 first (most common location)
        subcode03 = product_details.get('Subcode03', '').strip()
        print(f"[EXTRACT] Checking Subcode03 for PRESSURBAL: '{subcode03}'")
        
        if subcode03 and subcode03 != 'N/A':
            if 'PRESSURBAL' in subcode03.upper():
                match = re.search(r'PRESSURBAL\s*(\d+)', subcode03.upper())
                if match:
                    pressur_bal = match.group(1)
                    print(f"[EXTRACT] PRESSURBAL found in Subcode03: {pressur_bal}")
                else:
                    pressur_bal = subcode03
                    print(f"[EXTRACT] Using Subcode03 as pressur_bal: {pressur_bal}")
            else:
                pressur_bal = subcode03
                print(f"[EXTRACT] Using Subcode03 as pressur_bal: {pressur_bal}")
        
        # If not found in Subcode03, check other subcodes
        if pressur_bal is None:
            for i in range(1, 11):
                subcode_key = f'Subcode{str(i).zfill(2)}'
                if subcode_key != 'Subcode03':
                    subcode_value = product_details.get(subcode_key, '').strip()
                    if subcode_value and subcode_value != 'N/A':
                        if 'PRESSURBAL' in subcode_value.upper():
                            match = re.search(r'PRESSURBAL\s*(\d+)', subcode_value.upper())
                            if match:
                                pressur_bal = match.group(1)
                                print(f"[EXTRACT] PRESSURBAL found in {subcode_key}: {pressur_bal}")
                                break
    
    # ========== EXTRACT PRESSURBAL FROM KIT ELEMENTS (Fallback) ==========
    if pressur_bal is None and kit_elements:
        print("[EXTRACT] Checking kit elements for pressure info...")
        for kit in kit_elements:
            element_desc = kit.get('ELEMENTDESC', '').strip()
            if element_desc and 'PRESSURE' in element_desc.upper():
                match = re.search(r'(\d+)', element_desc)
                if match:
                    pressur_bal = match.group(1)
                    print(f"[EXTRACT] Pressure found in ELEMENTDESC: {pressur_bal}")
                    break
    
    # ========== APPLY DEFAULTS IF NEEDED ==========
    if pressur_bal is None:
        pressur_bal = '1'
        print("[EXTRACT] Using default pressur_bal: 1")
    
    if pl1 is None:
        pl1 = '1'
        print("[EXTRACT] Using default pl1: 1")
    
    # If no packing_sequence found, use pl1 as fallback
    if not packing_sequence:
        packing_sequence = pl1
    
    print(f"[EXTRACT] FINAL - PressurBal: {pressur_bal}, PL1: {pl1}, PackingSeq: {packing_sequence}\n")
    return pressur_bal, pl1, packing_sequence


# ---------------------- HELPER: BUILD IMAGE URL ----------------------
def build_image_url(element, customer_data, product_details, production_order_code, production_demand_code, pallet_number, box_number, kit_elements=None):
    """Generate media path with new structure using PACKINGSEQUENCE"""
    import re
    
    if customer_data is None:
        customer_data = {}
    
    customer_name = customer_data.get('CustomerName', '').strip() if customer_data.get('CustomerName') else 'UNKNOWN'
    customer_po = customer_data.get('CustomerPO', '').strip() if customer_data.get('CustomerPO') else 'NONE'
    
    if not customer_po or customer_po == '-':
        customer_po = 'NONE'
    
    customer_clean = re.sub(r'[^\w\s-]', '', customer_name).strip().upper()
    customer_slug = customer_clean.replace(' ', '-').replace('--', '-')
    
    po_clean = customer_po.upper()
    order_clean = production_order_code.strip().upper()
    demand_clean = production_demand_code.strip().upper()
    
    if product_details is None:
        product_details = {}
    
    # Extract values including packing_sequence
    pressur_bal, pl1, packing_sequence = extract_pressur_bal_and_pl1(product_details, kit_elements)
    
    # Clean values for folder names
    pressur_bal_clean = re.sub(r'\D', '', str(pressur_bal)) or '1'
    
    # Use packing_sequence for box folder (this is the key change!)
    if packing_sequence and packing_sequence != 'N/A':
        # Clean packing sequence for folder name (remove special chars)
        box_folder_value = re.sub(r'[^\w\-]', '', packing_sequence).strip()
        if not box_folder_value:
            box_folder_value = pl1
    else:
        box_folder_value = pl1
    
    pallet_clean = str(pallet_number).strip().upper()
    box_clean = str(box_number).strip().upper()
    
    element_desc = element.get('ELEMENTDESC', 'no_description').strip()
    element_clean = re.sub(r'[^\w\s-]', '', element_desc).strip().upper()
    element_slug = element_clean.replace(' ', '_').replace('__', '_')
    
    subcode03 = product_details.get('Subcode03', '').strip()
    demand_folder = f"{demand_clean}_{subcode03}"
    
    # Build folder structure with PACKINGSEQUENCE value
    folder_structure = f"{customer_slug}--{po_clean}/{order_clean}/{demand_folder}/PALLET_{pallet_clean}_{subcode03}/BOX_{box_clean}_{box_folder_value}"
    
    print(f"[FOLDER] Generated folder: {folder_structure}")
    return folder_structure, element_slug


# ---------------------- BUILD COMMON FOLDER PATH ----------------------
def build_common_folder_path(customer_data, product_details, production_order_code, production_demand_code, pallet_number, box_number, kit_elements=None):
    """Generate common folder path structure using PACKINGSEQUENCE"""
    import re
    
    if customer_data is None:
        customer_data = {}
    
    customer_name = customer_data.get('CustomerName', '').strip() if customer_data.get('CustomerName') else 'UNKNOWN'
    customer_po = customer_data.get('CustomerPO', '').strip() if customer_data.get('CustomerPO') else 'NONE'
    
    if not customer_po or customer_po == '-':
        customer_po = 'NONE'
    
    customer_clean = re.sub(r'[^\w\s-]', '', customer_name).strip().upper()
    customer_slug = customer_clean.replace(' ', '-').replace('--', '-')
    
    po_clean = customer_po.upper()
    order_clean = production_order_code.strip().upper()
    demand_clean = production_demand_code.strip().upper()
    
    if product_details is None:
        product_details = {}
    
    pressur_bal, pl1, packing_sequence = extract_pressur_bal_and_pl1(product_details, kit_elements)
    pressur_bal_clean = re.sub(r'\D', '', str(pressur_bal)) or '1'
    
    # Use packing_sequence for box folder
    if packing_sequence and packing_sequence != 'N/A':
        box_folder_value = re.sub(r'[^\w\-]', '', packing_sequence).strip()
        if not box_folder_value:
            box_folder_value = pl1
    else:
        box_folder_value = pl1
    
    subcode03 = product_details.get('Subcode03', '').strip()
    demand_folder = f"{demand_clean}_{subcode03}"
    pallet_clean = str(pallet_number).strip().upper()
    box_clean = str(box_number).strip().upper()
    
    folder_path = f"{customer_slug}--{po_clean}/{order_clean}/{demand_folder}/PALLET_{pallet_clean}_{subcode03}/BOX_{box_clean}_{box_folder_value}"
    
    return folder_path


# ---------------------- CHECK IMAGE EXISTS ----------------------
def check_image_exists(folder_structure, element_slug, element_desc):
    directory_path = os.path.join(settings.MEDIA_ROOT, folder_structure)
    
    if not os.path.exists(directory_path):
        return None
    
    try:
        files = os.listdir(directory_path)
        
        for file in files:
            file_name = os.path.splitext(file)[0]
            if file_name == element_desc:
                return f"{settings.MEDIA_URL}{folder_structure}/{file}".replace('\\', '/')
        
        return None
            
    except Exception as e:
        print(f"Error: {e}")
        return None


# ---------------------- CHECK HUMAN IMAGE EXISTS ----------------------
def check_human_image_exists(human_folder_structure, element_desc):
    """Check if human image exists - checks network path only (no human_faces folder needed)"""
    
    # Check network path directly
    try:
        network_base = r"\\192.168.4.32\Corekit"
        # Remove 'human_faces/' prefix if present
        clean_folder = human_folder_structure.replace('human_faces/', '')
        network_directory = os.path.join(network_base, clean_folder)
        
        if os.path.exists(network_directory):
            files = os.listdir(network_directory)
            for file in files:
                file_name = os.path.splitext(file)[0]
                # Check both with and without 'fc_' prefix
                if file_name == element_desc or file_name == f"fc_{element_desc}":
                    # Return the network path URL
                    found_url = f"{settings.MEDIA_URL}{clean_folder}/{file}".replace('\\', '/')
                    print(f"[HUMAN IMAGE FOUND IN NETWORK] {found_url}")
                    return found_url
    except Exception as e:
        print(f"Error checking network human image: {e}")
    
    print(f"[HUMAN IMAGE NOT FOUND] {element_desc}")
    return None


# ---------------------- FETCH DATA ----------------------
def fetch_data(request):
    if request.method == 'POST':
        production_order_code = request.POST.get('production_order_code', '').strip()
        production_demand_code = request.POST.get('production_demand_code', '').strip()
        pallet_number = request.POST.get('pallet_number', '1').strip()
        box_number = request.POST.get('box_number', '1').strip()

        customer_data = fetch_customer_data(production_order_code, production_demand_code)
        product_details = fetch_product_details(production_order_code, production_demand_code)
        kit_elements = fetch_kit_elements(production_order_code, production_demand_code, pallet_number, box_number)
        
        # Extract PressurBal, PL1 and packing_sequence with kit_elements
        pressur_bal, pl1, packing_sequence = extract_pressur_bal_and_pl1(product_details, kit_elements)
        print(f"Extracted PressurBal: {pressur_bal}, PL1: {pl1}, PackingSeq: {packing_sequence}")
        
        if product_details:
            product_details['PressurBal'] = pressur_bal
            product_details['PL1'] = pl1
            product_details['PackingSequence'] = packing_sequence

        # Process each element for element images
        for element in kit_elements:
            folder_structure, element_slug = build_image_url(
                element, 
                customer_data if customer_data else {}, 
                product_details if product_details else {}, 
                production_order_code, 
                production_demand_code, 
                pallet_number, 
                box_number,
                kit_elements  # Pass kit_elements for extraction
            )
            
            # Store folder structure in element for later use
            element['folder_structure'] = folder_structure
            
            element_desc = element.get('ELEMENTDESC', '').strip()
            image_url = check_image_exists(folder_structure, element_slug, element_desc)
            if image_url:
                element['image_url'] = image_url
                element['has_image'] = True
            else:
                element['image_url'] = None
                element['has_image'] = False
        
        # Process each element's human image separately
        for element in kit_elements:
            current_ply = element.get('ELEMENTDESC', '').strip()
            
            if current_ply:
                # Use the folder_structure already stored in element
                folder_structure = element.get('folder_structure', '')
                
                if not folder_structure:
                    # Fallback: rebuild folder structure
                    folder_structure, _ = build_image_url(
                        element, 
                        customer_data if customer_data else {}, 
                        product_details if product_details else {}, 
                        production_order_code, 
                        production_demand_code, 
                        pallet_number, 
                        box_number,
                        kit_elements
                    )
                
                # Use folder_structure directly without human_faces prefix
                human_image_url = check_human_image_exists(folder_structure, current_ply)
                
                # Store human image info in element
                element['human_image_url'] = human_image_url
                element['has_human_image'] = human_image_url is not None
                element['human_folder'] = folder_structure  # Store folder without human_faces prefix
            else:
                element['human_image_url'] = None
                element['has_human_image'] = False

        context = {
            'customer_data': customer_data if customer_data else {
                'CustomerName': 'Not Available',
                'CustomerPO': 'Not Available',
                'CustomerCode': 'Not Available'
            },
            'product_details': product_details if product_details else {
                'ItemType': 'Not Available',
                'Subcode01': 'N/A',
                'Subcode02': 'N/A',
                'Subcode03': 'N/A',
                'Subcode04': 'N/A',
                'Subcode05': 'N/A',
                'PressurBal': '',
                'PL1': '',
                'PackingSequence': ''
            },
            'kit_elements': kit_elements or [],
            'production_order_code': production_order_code,
            'production_demand_code': production_demand_code,
            'pallet_number': pallet_number,
            'box_number': box_number,
            'packing_sequence': packing_sequence,
            'MEDIA_URL': settings.MEDIA_URL
        }

        if not any([customer_data, product_details, kit_elements]):
            context['error'] = "No data found for the provided codes"
            return render(request, 'fetch_data.html', context)

        return render(request, 'view_data.html', context)

    return render(request, 'fetch_data.html')


# ---------------------- VIEW DATA ----------------------
def view_data(request):
    if request.method == 'POST':
        production_order_code = request.POST.get('production_order_code', '').strip()
        production_demand_code = request.POST.get('production_demand_code', '').strip()
        pallet_number = request.POST.get('pallet_number', '1').strip()
        box_number = request.POST.get('box_number', '1').strip()

        customer_data = fetch_customer_data(production_order_code, production_demand_code)
        product_details = fetch_product_details(production_order_code, production_demand_code)
        kit_elements = fetch_kit_elements(production_order_code, production_demand_code, pallet_number, box_number)
        
        # Extract PressurBal, PL1 and packing_sequence with kit_elements
        pressur_bal, pl1, packing_sequence = extract_pressur_bal_and_pl1(product_details, kit_elements)
        
        if product_details:
            product_details['PressurBal'] = pressur_bal
            product_details['PL1'] = pl1
            product_details['PackingSequence'] = packing_sequence

        for element in kit_elements:
            folder_structure, element_slug = build_image_url(
                element, 
                customer_data if customer_data else {}, 
                product_details if product_details else {}, 
                production_order_code, 
                production_demand_code, 
                pallet_number, 
                box_number,
                kit_elements
            )
            
            element['folder_structure'] = folder_structure
            
            element_desc = element.get('ELEMENTDESC', '').strip()
            image_url = check_image_exists(folder_structure, element_slug, element_desc)
            if image_url:
                element['image_url'] = image_url
                element['has_image'] = True
            else:
                element['image_url'] = None
                element['has_image'] = False
        
        # Process each element's human image separately
        for element in kit_elements:
            current_ply = element.get('ELEMENTDESC', '').strip()
            
            if current_ply:
                folder_structure = element.get('folder_structure', '')
                
                if not folder_structure:
                    folder_structure, _ = build_image_url(
                        element, 
                        customer_data if customer_data else {}, 
                        product_details if product_details else {}, 
                        production_order_code, 
                        production_demand_code, 
                        pallet_number, 
                        box_number,
                        kit_elements
                    )
                
                human_image_url = check_human_image_exists(folder_structure, current_ply)
                
                element['human_image_url'] = human_image_url
                element['has_human_image'] = human_image_url is not None
                element['human_folder'] = folder_structure
            else:
                element['human_image_url'] = None
                element['has_human_image'] = False

        context = {
            'customer_data': customer_data if customer_data else {
                'CustomerName': 'Not Available',
                'CustomerPO': 'Not Available',
                'CustomerCode': 'Not Available'
            },
            'product_details': product_details if product_details else {
                'ItemType': 'Not Available',
                'Subcode01': 'N/A',
                'Subcode02': 'N/A',
                'Subcode03': 'N/A',
                'Subcode04': 'N/A',
                'Subcode05': 'N/A',
                'PressurBal': '',
                'PL1': '1',
                'PackingSequence': ''
            },
            'kit_elements': kit_elements or [],
            'production_order_code': production_order_code,
            'production_demand_code': production_demand_code,
            'pallet_number': pallet_number,
            'box_number': box_number,
            'packing_sequence': packing_sequence,
            'MEDIA_URL': settings.MEDIA_URL
        }

        return render(request, 'view_data.html', context)

    # GET request handling (same as POST but with GET parameters)
    production_order_code = request.GET.get('production_order_code', '').strip()
    production_demand_code = request.GET.get('production_demand_code', '').strip()
    pallet_number = request.GET.get('pallet_number', '1').strip()
    box_number = request.GET.get('box_number', '1').strip()

    if production_order_code and production_demand_code:
        customer_data = fetch_customer_data(production_order_code, production_demand_code)
        product_details = fetch_product_details(production_order_code, production_demand_code)
        kit_elements = fetch_kit_elements(production_order_code, production_demand_code, pallet_number, box_number)
        
        pressur_bal, pl1, packing_sequence = extract_pressur_bal_and_pl1(product_details, kit_elements)
        
        if product_details:
            product_details['PressurBal'] = pressur_bal
            product_details['PL1'] = pl1
            product_details['PackingSequence'] = packing_sequence

        for element in kit_elements:
            folder_structure, element_slug = build_image_url(
                element, 
                customer_data if customer_data else {}, 
                product_details if product_details else {}, 
                production_order_code, 
                production_demand_code, 
                pallet_number, 
                box_number,
                kit_elements
            )
            
            element['folder_structure'] = folder_structure
            
            element_desc = element.get('ELEMENTDESC', '').strip()
            image_url = check_image_exists(folder_structure, element_slug, element_desc)
            if image_url:
                element['image_url'] = image_url
                element['has_image'] = True
            else:
                element['image_url'] = None
                element['has_image'] = False
        
        for element in kit_elements:
            current_ply = element.get('ELEMENTDESC', '').strip()
            
            if current_ply:
                folder_structure = element.get('folder_structure', '')
                
                if not folder_structure:
                    folder_structure, _ = build_image_url(
                        element, 
                        customer_data if customer_data else {}, 
                        product_details if product_details else {}, 
                        production_order_code, 
                        production_demand_code, 
                        pallet_number, 
                        box_number,
                        kit_elements
                    )
                
                human_image_url = check_human_image_exists(folder_structure, current_ply)
                
                element['human_image_url'] = human_image_url
                element['has_human_image'] = human_image_url is not None
                element['human_folder'] = folder_structure
            else:
                element['human_image_url'] = None
                element['has_human_image'] = False
        pressur_bal, pl1, packing_sequence = extract_pressur_bal_and_pl1(product_details, kit_elements)
        context = {
            'customer_data': customer_data if customer_data else {
                'CustomerName': 'Not Available',
                'CustomerPO': 'Not Available',
                'CustomerCode': 'Not Available'
            },
            'product_details': product_details if product_details else {
                'ItemType': 'Not Available',
                'Subcode01': 'N/A',
                'Subcode02': 'N/A',
                'Subcode03': 'N/A',
                'Subcode04': 'N/A',
                'Subcode05': 'N/A',
                'PressurBal': '',
                'PL1': '1',
                'PackingSequence': ''
            },
            'kit_elements': kit_elements or [],
            'production_order_code': production_order_code,
            'production_demand_code': production_demand_code,
            'pallet_number': pallet_number,
            'box_number': box_number,
            'packing_sequence': packing_sequence,
            'MEDIA_URL': settings.MEDIA_URL
        }

        return render(request, 'view_data.html', context)

    return render(request, 'fetch_data.html')


def write_timing_log(log_data):
    """
    Write timing information to a text file
    """
    # Create logs directory in project root
    logs_dir = os.path.join(settings.BASE_DIR, 'logs')
    
    # Ensure directory exists
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
        print(f"[LOG] Created logs directory at: {logs_dir}")
    
    # Create filename with current date
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    log_filename = f"capture_times_{today}.txt"
    log_filepath = os.path.join(logs_dir, log_filename)
    
    # Get current timestamp
    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Calculate durations if timestamps are provided
    
    back_duration = log_data.get('back_capture_duration', 'N/A')
    front_duration = log_data.get('front_capture_duration', 'N/A')
    total_duration = log_data.get('total_duration', 'N/A')
    between_duration = log_data.get('between_captures_duration', 'N/A')
    upload_duration = log_data.get('upload_duration', 'N/A')
    
    # Format the log entry
    log_entry = f"""
{'='*80}
TIMESTAMP: {current_time}
{'='*80}

ELEMENT INFORMATION:
-------------------
Element Description: {log_data.get('element_desc', 'N/A')}
Image Type: {log_data.get('image_type', 'N/A')}
Status: {log_data.get('status', 'N/A')}

ORDER INFORMATION:
-----------------
Order Code: {log_data.get('order_code', 'N/A')}
Demand Code: {log_data.get('demand_code', 'N/A')}

CUSTOMER INFORMATION:
--------------------
Customer Name: {log_data.get('customer_name', 'N/A')}
Customer PO: {log_data.get('customer_po', 'N/A')}

CONTAINER INFORMATION:
---------------------
Pallet Number: {log_data.get('pallet_number', 'N/A')}
Box Number: {log_data.get('box_number', 'N/A')}

TIMING INFORMATION:
------------------
Capture Start Time: {log_data.get('capture_start_time', 'N/A')}
Back Camera Capture: {log_data.get('back_capture_time', 'N/A')}
Front Camera Capture: {log_data.get('front_capture_time', 'N/A')}
Upload Start Time: {log_data.get('upload_start_time', 'N/A')}
Upload Complete Time: {log_data.get('upload_complete_time', 'N/A')}

DURATIONS (seconds):
-------------------
Total Duration (Start to Upload): {total_duration}
Time to Back Camera Capture: {back_duration}
Time to Front Camera Capture: {front_duration}
Time Between Captures: {between_duration}
Upload Processing Time: {upload_duration}

SYSTEM INFORMATION:
------------------
Folder Path: {log_data.get('folder_path', 'N/A')}
IP Address: {log_data.get('ip_address', 'N/A')}
User Agent: {log_data.get('user_agent', 'N/A')[:100]}

{'='*80}

"""
    
    # Write to file
    try:
        with open(log_filepath, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        print(f"[LOG] Successfully wrote to: {log_filepath}")
        return True
    except Exception as e:
        print(f"[LOG ERROR] Failed to write: {e}")
        return False



# ---------------------- SIMPLE LOG FUNCTION (DIRECT CALL) ----------------------
def log_capture_time_simple(element_desc, order_code, demand_code, pallet_number, 
                            box_number, capture_start, upload_complete, 
                            status="success", extra_data=None):
    """
    Simple function to log capture time directly
    """
    logs_dir = os.path.join(settings.BASE_DIR, 'logs')
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    log_filepath = os.path.join(logs_dir, f"capture_times_{today}.txt")
    
    # Calculate duration
    duration = "N/A"
    if capture_start and upload_complete:
        try:
            start = datetime.datetime.fromisoformat(capture_start.replace('Z', '+00:00'))
            end = datetime.datetime.fromisoformat(upload_complete.replace('Z', '+00:00'))
            duration = f"{(end - start).total_seconds():.3f}"
        except:
            pass
    
    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    log_entry = f"""
[{current_time}] CAPTURE LOG
Element: {element_desc}
Order: {order_code} | Demand: {demand_code}
Pallet: {pallet_number} | Box: {box_number}
Capture Start: {capture_start}
Upload Complete: {upload_complete}
Total Duration: {duration} seconds
Status: {status}
{'='*60}
"""
    
    if extra_data:
        log_entry += f"Extra: {extra_data}\n{'='*60}\n"
    
    try:
        with open(log_filepath, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        print(f"[SIMPLE LOG] Saved: {log_filepath}")
        return True
    except Exception as e:
        print(f"[SIMPLE LOG ERROR] {e}")
        return False


def log_to_network_file(log_data):
    """
    Save timing logs directly to network path: \\192.168.4.32\Corekit\logs\
    Creates folder automatically if it doesn't exist
    """
    # Network log path
    network_base = r"\\192.168.4.32\Corekit"
    logs_dir = os.path.join(network_base, "logs")
    
    # Create logs directory if it doesn't exist
    try:
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir, exist_ok=True)
            print(f"[LOG] Created logs directory: {logs_dir}")
    except Exception as e:
        print(f"[LOG ERROR] Could not create logs directory: {e}")
        # Fallback to local logs if network fails
        logs_dir = os.path.join(settings.BASE_DIR, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
    
    # Create filename with date
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    log_filename = f"capture_upload_times_{today}.txt"
    log_filepath = os.path.join(logs_dir, log_filename)
    
    # Current timestamp
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Format the log entry
    log_entry = f"""
{'='*80}
[{timestamp}] IMAGE CAPTURE & UPLOAD LOG
{'='*80}

ELEMENT INFORMATION:
-------------------
Element Description: {log_data.get('element_desc', 'N/A')}
Image Type: {log_data.get('image_type', 'N/A')}
Status: {log_data.get('status', 'N/A')}

ORDER INFORMATION:
-----------------
Order Code: {log_data.get('order_code', 'N/A')}
Demand Code: {log_data.get('demand_code', 'N/A')}

CUSTOMER INFORMATION:
--------------------
Customer Name: {log_data.get('customer_name', 'N/A')}
Customer PO: {log_data.get('customer_po', 'N/A')}

CONTAINER INFORMATION:
---------------------
Pallet Number: {log_data.get('pallet_number', 'N/A')}
Box Number: {log_data.get('box_number', 'N/A')}

TIME INFORMATION:
----------------
Capture Start Time: {log_data.get('capture_start_time', 'N/A')}
Back Camera Capture: {log_data.get('back_capture_time', 'N/A')}
Front Camera Capture: {log_data.get('front_capture_time', 'N/A')}
Upload Start Time: {log_data.get('upload_start_time', 'N/A')}
Upload Complete Time: {log_data.get('upload_complete_time', 'N/A')}

DURATIONS (seconds):
-------------------
Total Duration (Start to Upload): {log_data.get('total_duration', 'N/A')}
Time to Back Camera Capture: {log_data.get('back_capture_duration', 'N/A')}
Time to Front Camera Capture: {log_data.get('front_capture_duration', 'N/A')}
Time Between Captures: {log_data.get('between_captures_duration', 'N/A')}
Upload Processing Time: {log_data.get('upload_duration', 'N/A')}

SYSTEM INFORMATION:
------------------
Folder Path: {log_data.get('folder_path', 'N/A')}
IP Address: {log_data.get('ip_address', 'N/A')}

{'='*80}

"""
    
    # Write to network log file
    try:
        with open(log_filepath, 'a', encoding='utf-8') as log_file:
            log_file.write(log_entry)
        print(f"[LOG] Successfully saved to: {log_filepath}")
        return True
    except Exception as e:
        print(f"[LOG ERROR] Failed to write: {e}")
        return False



def log_simple_message(message, log_type="info"):
    """Simple function to log quick messages to network"""
    network_base = r"\\192.168.4.32\Corekit"
    logs_dir = os.path.join(network_base, "logs")
    
    try:
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir, exist_ok=True)
    except:
        # Fallback to local
        logs_dir = os.path.join(settings.BASE_DIR, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
    
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    log_filepath = os.path.join(logs_dir, f"simple_log_{today}.txt")
    
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    
    try:
        with open(log_filepath, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] [{log_type.upper()}] {message}\n")
        return True
    except Exception as e:
        print(f"Simple log error: {e}")
        return False


# ---------------------- UPLOAD ELEMENT IMAGE ----------------------
@csrf_exempt
def upload_element_image(request):
    if request.method == 'POST':
        # Log start of upload
        log_simple_message("upload_element_image called", "debug")
        
        try:
            # Get timing information
            capture_start_time = request.POST.get('capture_start_time')
            back_capture_time = request.POST.get('back_capture_time')
            front_capture_time = request.POST.get('front_capture_time')
            upload_start_time = request.POST.get('upload_start_time')
            
            element_desc = request.POST.get('element_desc', '').strip()
            is_human_image = request.POST.get('is_human_image') == 'true'
            
            # Get order information
            production_order_code = request.POST.get('production_order_code', '').strip()
            production_demand_code = request.POST.get('production_demand_code', '').strip()
            pallet_number = request.POST.get('pallet_number', '').strip()
            box_number = request.POST.get('box_number', '').strip()
            
            # Log basic info
            log_simple_message(f"Processing: {element_desc} (Human: {is_human_image})", "info")
            log_simple_message(f"Order: {production_order_code}, Demand: {production_demand_code}", "info")
            log_simple_message(f"Capture start time: {capture_start_time}", "timing")
            
            # Set filename
            if is_human_image:
                filename = f"fc_{element_desc}.jpeg"
            else:
                filename = f"{element_desc}.jpeg"

            image_data = request.POST.get('element_image')
            
            if not image_data:
                log_simple_message("No image data received", "error")
                return JsonResponse({'status': 'error', 'message': 'No image data'}, status=400)

            # Dummy class for build_image_url
            class Dummy:
                def __init__(self, desc):
                    self.desc = desc
                def get(self, key, default):
                    return self.desc if key == 'ELEMENTDESC' else default

            dummy = Dummy(element_desc)

            # Fetch data
            from .utils.db_queries import fetch_customer_data, fetch_product_details, fetch_kit_elements
            customer_data = fetch_customer_data(production_order_code, production_demand_code)
            product_details = fetch_product_details(production_order_code, production_demand_code)
            kit_elements = fetch_kit_elements(production_order_code, production_demand_code, pallet_number, box_number)

            # Build folder structure
            folder_structure, _ = build_image_url(
                dummy,
                customer_data or {},
                product_details or {},
                production_order_code,
                production_demand_code,
                pallet_number,
                box_number,
                kit_elements
            )
            
            log_simple_message(f"Folder structure: {folder_structure}", "path")

            image_bytes = base64.b64decode(image_data)

            # Save the image
            if is_human_image:
                # Save only to network (no human_faces folder needed)
                network_base = r"\\192.168.4.32\Corekit"
                folder_structure_clean = folder_structure.strip('/\\')
                network_folder = os.path.join(network_base, folder_structure_clean)
                filepath = os.path.join(network_folder, filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                
                with open(filepath, 'wb') as f:
                    f.write(image_bytes)
                
                log_simple_message(f"Human image saved to network: {filepath}", "success")
            else:
                # Save element image to local media
                main_path = os.path.join(settings.MEDIA_ROOT, folder_structure)
                os.makedirs(main_path, exist_ok=True)
                filepath = os.path.join(main_path, filename)
                
                with open(filepath, 'wb') as f:
                    f.write(image_bytes)
                
                log_simple_message(f"Element image saved to: {filepath}", "success")
            
            # LOG THE TIMING INFORMATION TO NETWORK
            upload_complete_time = datetime.datetime.now().isoformat()
            
            # Get customer name and PO
            customer_name = customer_data.get('CustomerName', 'UNKNOWN') if customer_data else 'UNKNOWN'
            customer_po = customer_data.get('CustomerPO', 'NONE') if customer_data else 'NONE'
            
            # Extract PL value
            pl_match = re.search(r'BOX_\d+_(\d+)', folder_structure)
            pl_value = pl_match.group(1) if pl_match else '1'
            
            # Calculate durations
            total_duration = "N/A"
            back_capture_duration = "N/A"
            front_capture_duration = "N/A"
            between_captures_duration = "N/A"
            upload_duration = "N/A"
            
            if capture_start_time and upload_complete_time:
                try:
                    start = datetime.datetime.fromisoformat(capture_start_time.replace('Z', '+00:00'))
                    end = datetime.datetime.fromisoformat(upload_complete_time.replace('Z', '+00:00'))
                    total_duration = f"{(end - start).total_seconds():.3f}"
                    log_simple_message(f"Total duration for {element_desc}: {total_duration} seconds", "duration")
                except Exception as e:
                    log_simple_message(f"Could not calculate total duration: {e}", "warning")
            
            if capture_start_time and back_capture_time:
                try:
                    start = datetime.datetime.fromisoformat(capture_start_time.replace('Z', '+00:00'))
                    back = datetime.datetime.fromisoformat(back_capture_time.replace('Z', '+00:00'))
                    back_capture_duration = f"{(back - start).total_seconds():.3f}"
                except:
                    pass
            
            if capture_start_time and front_capture_time:
                try:
                    start = datetime.datetime.fromisoformat(capture_start_time.replace('Z', '+00:00'))
                    front = datetime.datetime.fromisoformat(front_capture_time.replace('Z', '+00:00'))
                    front_capture_duration = f"{(front - start).total_seconds():.3f}"
                except:
                    pass
            
            if back_capture_time and front_capture_time:
                try:
                    back = datetime.datetime.fromisoformat(back_capture_time.replace('Z', '+00:00'))
                    front = datetime.datetime.fromisoformat(front_capture_time.replace('Z', '+00:00'))
                    between_captures_duration = f"{abs((front - back).total_seconds()):.3f}"
                except:
                    pass
            
            if upload_start_time and upload_complete_time:
                try:
                    up_start = datetime.datetime.fromisoformat(upload_start_time.replace('Z', '+00:00'))
                    up_end = datetime.datetime.fromisoformat(upload_complete_time.replace('Z', '+00:00'))
                    upload_duration = f"{(up_end - up_start).total_seconds():.3f}"
                except:
                    pass
            
            # Prepare log data for network storage
            log_data = {
                'element_desc': element_desc,
                'image_type': 'Human Image' if is_human_image else 'Element Image',
                'status': 'success',
                'order_code': production_order_code,
                'demand_code': production_demand_code,
                'customer_name': customer_name,
                'customer_po': customer_po,
                'pallet_number': pallet_number,
                'box_number': box_number,
                'pl_value': pl_value,
                'capture_start_time': capture_start_time,
                'back_capture_time': back_capture_time,
                'front_capture_time': front_capture_time,
                'upload_start_time': upload_start_time,
                'upload_complete_time': upload_complete_time,
                'total_duration': total_duration,
                'back_capture_duration': back_capture_duration,
                'front_capture_duration': front_capture_duration,
                'between_captures_duration': between_captures_duration,
                'upload_duration': upload_duration,
                'folder_path': folder_structure,
                'ip_address': request.META.get('REMOTE_ADDR', 'N/A')
            }
            
            # Save to network log file
            log_to_network_file(log_data)
            
            return JsonResponse({
                'status': 'success',
                'filename': filename,
                'path': str(filepath),
                'message': 'Image saved successfully',
                'total_duration': total_duration,
                'log_saved_to': r'\\192.168.4.32\Corekit\logs'
            })

        except Exception as e:
            error_msg = f"Upload error: {str(e)}"
            log_simple_message(error_msg, "error")
            import traceback
            traceback.print_exc()
            
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)



# ---------------------- DELETE IMAGE ----------------------
@csrf_exempt
def delete_element_image(request):
    if request.method == 'POST':
        try:
            image_url = request.POST.get('image_url', '').strip()
            is_human_image = request.POST.get('is_human_image') == 'true'
            element_desc = request.POST.get('element_desc', '').strip()
            production_order_code = request.POST.get('production_order_code', '').strip()
            production_demand_code = request.POST.get('production_demand_code', '').strip()
            pallet_number = request.POST.get('pallet_number', '').strip()
            box_number = request.POST.get('box_number', '').strip()
            
            if not element_desc:
                return JsonResponse({'status': 'error', 'message': 'Element description is required'}, status=400)
            
            class Dummy:
                def __init__(self, desc):
                    self.desc = desc
                def get(self, key, default):
                    return self.desc if key == 'ELEMENTDESC' else default
            
            dummy = Dummy(element_desc)
            
            customer_data = fetch_customer_data(production_order_code, production_demand_code)
            product_details = fetch_product_details(production_order_code, production_demand_code)
            kit_elements = fetch_kit_elements(production_order_code, production_demand_code, pallet_number, box_number)
            
            folder_structure, _ = build_image_url(
                dummy,
                customer_data or {},
                product_details or {},
                production_order_code,
                production_demand_code,
                pallet_number,
                box_number,
                kit_elements
            )
            
            deleted_files = []
            failed_files = []
            
            # Delete element image (local only)
            element_filename = f"{element_desc}.jpeg"
            main_folder = os.path.join(settings.MEDIA_ROOT, folder_structure)
            element_file_path = os.path.join(main_folder, element_filename)
            
            if os.path.exists(element_file_path):
                try:
                    os.remove(element_file_path)
                    deleted_files.append(f"Element image: {element_filename}")
                except Exception as e:
                    failed_files.append(f"Element image: {str(e)}")
            
            # Delete human image from network only
            human_filename = f"fc_{element_desc}.jpeg"
            try:
                network_base = r"\\192.168.4.32\Corekit"
                folder_structure_clean = folder_structure.strip('/\\')
                network_folder = os.path.join(network_base, folder_structure_clean)
                network_file_path = os.path.join(network_folder, human_filename)
                
                if os.path.exists(network_file_path):
                    os.remove(network_file_path)
                    deleted_files.append(f"Human image (network): {human_filename}")
            except Exception as e:
                print(f"Error deleting network human image: {e}")
                failed_files.append(f"Human image (network): {str(e)}")
            
            # Log deletion time
            deletion_time = datetime.datetime.now()
            logs_dir = os.path.join(settings.BASE_DIR, 'logs')
            os.makedirs(logs_dir, exist_ok=True)
            today = datetime.datetime.now().strftime('%Y-%m-%d')
            log_filename = f"image_deletions_{today}.txt"
            log_filepath = os.path.join(logs_dir, log_filename)
            
            with open(log_filepath, 'a', encoding='utf-8') as log_file:
                log_file.write(f"""
{'='*80}
[{deletion_time.strftime('%Y-%m-%d %H:%M:%S')}] IMAGE DELETION
{'='*80}
Element: {element_desc}
Order: {production_order_code}
Demand: {production_demand_code}
Pallet: {pallet_number}
Box: {box_number}
Deleted Files: {', '.join(deleted_files)}
Failed: {', '.join(failed_files)}
{'='*80}

""")
            
            if deleted_files:
                message = f"Successfully deleted: {', '.join(deleted_files)}"
                if failed_files:
                    message += f" | Failed: {', '.join(failed_files)}"
                return JsonResponse({
                    'status': 'success', 
                    'message': message,
                    'deleted_files': deleted_files,
                    'failed_files': failed_files
                })
            else:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'No images found to delete'
                }, status=404)
                
        except Exception as e:
            print(f"Delete image error: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'status': 'error', 
                'message': f'Server error: {str(e)}'
            }, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)



@csrf_exempt
def save_timing_log_endpoint(request):
    """Endpoint to save timing log from frontend"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Prepare log data
            log_data = {
                'element_desc': data.get('element_desc', 'N/A'),
                'image_type': data.get('image_type', 'N/A'),
                'status': data.get('status', 'N/A'),
                'order_code': data.get('order_code', 'N/A'),
                'demand_code': data.get('demand_code', 'N/A'),
                'customer_name': data.get('customer_name', 'N/A'),
                'customer_po': data.get('customer_po', 'N/A'),
                'pallet_number': data.get('pallet_number', 'N/A'),
                'box_number': data.get('box_number', 'N/A'),
                'pl_value': data.get('pl_value', 'N/A'),
                'capture_start_time': data.get('capture_start_time', 'N/A'),
                'back_capture_time': data.get('back_capture_time', 'N/A'),
                'front_capture_time': data.get('front_capture_time', 'N/A'),
                'upload_start_time': data.get('upload_start_time', 'N/A'),
                'upload_complete_time': data.get('upload_complete_time', 'N/A'),
                'total_duration': data.get('total_duration', 'N/A'),
                'back_capture_duration': data.get('back_capture_duration', 'N/A'),
                'front_capture_duration': data.get('front_capture_duration', 'N/A'),
                'between_captures_duration': data.get('between_captures_duration', 'N/A'),
                'upload_duration': data.get('upload_duration', 'N/A'),
                'folder_path': data.get('folder_path', 'N/A'),
                'ip_address': request.META.get('REMOTE_ADDR', 'N/A'),
                'user_agent': request.META.get('HTTP_USER_AGENT', 'N/A')[:100]
            }
            
            # Save to text file
            log_time_to_text_file(log_data)
            
            return JsonResponse({'status': 'success', 'message': 'Log saved successfully'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)



@csrf_exempt
def test_network_logging(request):
    """Test endpoint to verify network logging is working"""
    if request.method == 'GET':
        try:
            # Test simple log
            log_simple_message("=== TEST LOG - Network logging test ===", "test")
            
            # Test detailed log
            test_data = {
                'element_desc': 'TEST_IMAGE',
                'image_type': 'Test',
                'status': 'test',
                'order_code': 'TEST_ORDER',
                'demand_code': 'TEST_DEMAND',
                'customer_name': 'TEST_CUSTOMER',
                'customer_po': 'TEST_PO',
                'pallet_number': '1',
                'box_number': '1',
                'pl_value': '1',
                'capture_start_time': datetime.datetime.now().isoformat(),
                'upload_complete_time': datetime.datetime.now().isoformat(),
                'total_duration': '0.001',
                'folder_path': 'TEST_FOLDER',
                'ip_address': request.META.get('REMOTE_ADDR', 'N/A')
            }
            
            result = log_to_network_file(test_data)
            
            if result:
                return JsonResponse({
                    'status': 'success',
                    'message': 'Network logging test successful',
                    'log_path': r'\\192.168.4.32\Corekit\logs'
                })
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Failed to write to network log'
                }, status=500)
                
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Use GET request'}, status=405)



# ---------------------- VIEW ALL LOGS ENDPOINT ----------------------
def view_logs(request):
    """View to display all log files from network"""
    network_base = r"\\192.168.4.32\Corekit"
    logs_dir = os.path.join(network_base, "logs")
    
    log_files = []
    if os.path.exists(logs_dir):
        log_files = [f for f in os.listdir(logs_dir) if f.endswith('.txt')]
        log_files.sort(reverse=True)
    
    return JsonResponse({
        'log_directory': logs_dir,
        'log_files': log_files,
        'total_logs': len(log_files)
    })
    
    
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from datetime import datetime
import os, base64


# BOX_IMAGE_PATH = (
#     r"D:\OneDrive - SKAPS INDUSTRIES INDIA PVT.LTD\Jay Vyas's files - Images from Server"
#     # r"D:\OneDrive - SKAPS INDUSTRIES INDIA PVT.LTD"
#     # r"\Jay Vyas's files - Extracted"
#     # r"\Server_Response_Box_img"
# )

BOX_IMAGE_PATH = os.path.join(settings.MEDIA_ROOT, "box_images")




@require_POST
@csrf_protect
def upload_box_capture(request):

    try:

        # --------------------------------------------------
        # Get image
        # ---------------------------------------------------

        image_data = request.POST.get("box_image")

        if not image_data:

            return JsonResponse({
                "status": "error",
                "message": "No image received."
            })


        # --------------------------------------------------
        # Get order information
        # --------------------------------------------------

        production_order_code = (
            request.POST.get(
                "production_order_code",
                "UNKNOWN_ORDER"
            )
        )

        production_demand_code = (
            request.POST.get(
                "production_demand_code",
                "UNKNOWN_DEMAND"
            )
        )

        pallet_number = (
            request.POST.get(
                "pallet_number",
                "UNKNOWN_PALLET"
            )
        )

        box_number = (
            request.POST.get(
                "box_number",
                "UNKNOWN_BOX"
            )
        )


        # --------------------------------------------------
        # Create folder if it doesn't exist
        # --------------------------------------------------

        os.makedirs(
            BOX_IMAGE_PATH,
            exist_ok=True
        )


        # --------------------------------------------------
        # Remove base64 prefix if present
        # --------------------------------------------------

        if "," in image_data:

            image_data = image_data.split(
                ",",
                1
            )[1]


        # --------------------------------------------------
        # Decode image
        # --------------------------------------------------

        image_bytes = base64.b64decode(
            image_data
        )


        # --------------------------------------------------
        # Create filename
        # --------------------------------------------------

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )


        filename = (
            f"{production_order_code}_"
            f"{production_demand_code}_"
            f"Pallet_{pallet_number}_"
            f"Box_{box_number}_"
            f"{timestamp}.jpg"
        )


        # Remove invalid Windows filename characters
        invalid_chars = '<>:"/\\|?*'


        for char in invalid_chars:

            filename = filename.replace(
                char,
                "_"
            )


        # --------------------------------------------------
        # Full path
        # --------------------------------------------------

        file_path = os.path.join(
            BOX_IMAGE_PATH,
            filename
        )


        # --------------------------------------------------
        # Save image
        # --------------------------------------------------

        with open(
            file_path,
            "wb"
        ) as image_file:

            image_file.write(
                image_bytes
            )


        print(
            "✅ Box image saved:",
            file_path
        )


        # --------------------------------------------------
        # Response
        # --------------------------------------------------

        return JsonResponse({

            "status": "success",

            "message":
                "Box image uploaded successfully.",

            "filepath":
                file_path,

            "filename":
                filename
        })


    except Exception as e:

        print(
            "❌ Box image upload error:",
            str(e)
        )


        return JsonResponse({

            "status": "error",

            "message":
                str(e)

        }, status=500)
        
        
        
        
# import os
# import shutil
# from django.conf import settings

# SOURCE_DIR = r"E:\Onedrive_it_intern\OneDrive - SKAPS INDUSTRIES INDIA PVT.LTD\Jay Vyas's files - Images from Server"
# DEST_DIR = r"\\192.168.4.32\Corekit"

# def move_files(production_order_code, production_demand_code, pallet_number, box_number, ply_orders):
#     # Step 1: Query database for ply_id → order_number mapping
#     order_clean = production_order_code.strip().upper()
#     demand_clean = production_demand_code.strip().upper()
#     pallet_clean = str(pallet_number).strip().upper()
#     box_clean = str(box_number).strip().upper()
#     mapping = {po.ply_id: po.order_number for po in ply_orders}

#     # Step 2: Loop through files in source
#     for filename in os.listdir(SOURCE_DIR):
#         if filename.endswith(".txt"):
#             # Extract ply_id from filename (assuming format Sl145.txt)
#             ply_id = filename.replace(".txt", "")

#             if ply_id in mapping:
#                 order_number = mapping[ply_id]

#                 # Step 3: Build destination folder path
#                 dest_folder = os.path.join(DEST_DIR, ply_id)

#                 if not os.path.exists(dest_folder):
#                     os.makedirs(dest_folder)

#                 # Step 4: Move file
#                 src_path = os.path.join(SOURCE_DIR, filename)
#                 dest_path = os.path.join(dest_folder, filename)
#                 shutil.move(src_path, dest_path)

#                 print(f"Moved {filename} for Ply {ply_id} (Order {order_number})")
#             else:
#                 print(f"No order found for {ply_id}, skipping {filename}")


import os
import shutil
import re
import time
import logging
from pathlib import Path
from datetime import datetime
# import watchdog.observers import Observer
# import watchdog.events import FileSystemEventHandler
from django.conf import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TextFileHandler(FileSystemEventHandler):
    """Handler for processing .txt files and moving them to appropriate ply folders."""
    
    def __init__(self, source_dir, base_destination_dir, order_number):
        """
        Initialize the file handler.
        
        Args:
            source_dir: Directory to watch for new .txt files
            base_destination_dir: Base directory containing ply folders
            order_number: The production order number to match
        """
        self.source_dir = Path(source_dir)
        self.base_dest_dir = Path(base_destination_dir)
        self.order_number = order_number
        self.processed_files = set()  # Track processed files to avoid duplicates
        
    def on_created(self, event):
        """Handle new file creation events."""
        if not event.is_directory and event.src_path.endswith('.txt'):
            self.process_file(event.src_path)
    
    def on_moved(self, event):
        """Handle file move events."""
        if not event.is_directory and event.dest_path.endswith('.txt'):
            self.process_file(event.dest_path)
    
    def process_file(self, file_path):
        """Process a single .txt file and move it to the appropriate folder."""
        file_path = Path(file_path)
        
        # Skip if already processed
        if str(file_path) in self.processed_files:
            return
        
        try:
            # Extract ply ID and sequence from filename
            filename = file_path.name
            ply_id, sequence = self.extract_ply_info(filename)
            
            if not ply_id:
                logger.warning(f"Could not extract ply ID from: {filename}")
                return
            
            # Find the destination folder
            dest_folder = self.find_destination_folder(ply_id)
            
            if not dest_folder:
                logger.warning(f"No destination folder found for ply ID: {ply_id}")
                return
            
            # Create destination folder if it doesn't exist
            dest_folder.mkdir(parents=True, exist_ok=True)
            
            # Move the file
            dest_path = dest_folder / filename
            
            # Check if file already exists
            if dest_path.exists():
                logger.warning(f"File already exists: {dest_path}")
                # Rename with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_name = f"{Path(filename).stem}_{timestamp}.txt"
                dest_path = dest_folder / new_name
                logger.info(f"Renaming to: {new_name}")
            
            # Move the file
            shutil.move(str(file_path), str(dest_path))
            self.processed_files.add(str(file_path))
            logger.info(f"✓ Moved {filename} to {dest_folder.name}")
            
            # Log the move to database if needed
            self.log_file_move(filename, ply_id, str(dest_folder))
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {str(e)}")
    
    def extract_ply_info(self, filename):
        """
        Extract ply ID and sequence from filename.
        
        Expected format: PLYID_SEQUENCE.txt or PLYID_ORDERNUMBER_SEQUENCE.txt
        Examples: SL145_001.txt, SL145_ORD123_001.txt, SL145.txt
        """
        # Remove extension
        name = Path(filename).stem
        
        # Try multiple patterns
        patterns = [
            # Pattern 1: PLYID_ORDERNUMBER_SEQUENCE (e.g., SL145_ORD123_001)
            rf'^([A-Za-z0-9]+)_{re.escape(self.order_number)}_(\d+)$',
            # Pattern 2: PLYID_SEQUENCE (e.g., SL145_001)
            r'^([A-Za-z0-9]+)_(\d+)$',
            # Pattern 3: PLYID (e.g., SL145)
            r'^([A-Za-z0-9]+)$',
            # Pattern 4: PLYID_ (e.g., SL145_)
            r'^([A-Za-z0-9]+)_',
        ]
        
        for pattern in patterns:
            match = re.match(pattern, name)
            if match:
                if len(match.groups()) == 2:
                    return match.group(1), match.group(2)
                else:
                    return match.group(1), None
        
        # Special case: Check if filename contains order number
        if self.order_number in name:
            parts = name.split('_')
            if len(parts) >= 1:
                return parts[0], parts[1] if len(parts) > 1 else None
        
        return None, None
    
    def find_destination_folder(self, ply_id):
        """
        Find the destination folder for a given ply ID.
        
        The folder should contain the ply ID in its name and the order number.
        """
        # Search for folders containing the ply ID and order number
        matches = []
        
        # Pattern 1: *PLYID*ORDERNUMBER* (most specific)
        pattern1 = f"*{ply_id}*{self.order_number}*"
        matches.extend(self.base_dest_dir.glob(pattern1))
        
        # Pattern 2: *PLYID* (less specific)
        if not matches:
            pattern2 = f"*{ply_id}*"
            matches.extend(self.base_dest_dir.glob(pattern2))
        
        # Pattern 3: Case-insensitive search
        if not matches:
            for folder in self.base_dest_dir.iterdir():
                if folder.is_dir():
                    folder_name = folder.name.upper()
                    if ply_id.upper() in folder_name and self.order_number.upper() in folder_name:
                        matches.append(folder)
            
            if not matches:
                # Try just ply ID case-insensitive
                for folder in self.base_dest_dir.iterdir():
                    if folder.is_dir() and ply_id.upper() in folder.name.upper():
                        matches.append(folder)
        
        # If multiple matches, use the most specific one
        if matches:
            # Sort by length (most specific first)
            matches.sort(key=lambda x: len(x.name), reverse=True)
            return matches[0]
        
        return None
    
    def log_file_move(self, filename, ply_id, dest_folder):
        """Log file move information (optional - can be extended to save to database)."""
        # You can extend this to save to your database
        # Example: FileMoveLog.objects.create(
        #     filename=filename,
        #     ply_id=ply_id,
        #     destination_folder=dest_folder,
        #     moved_at=datetime.now()
        # )
        pass


def process_existing_files(source_dir, base_destination_dir, order_number):
    """Process all existing .txt files in the source directory."""
    handler = TextFileHandler(source_dir, base_destination_dir, order_number)
    source_path = Path(source_dir)
    
    # Find all .txt files
    txt_files = list(source_path.glob('*.txt'))
    
    if not txt_files:
        logger.info("No existing .txt files found in source directory")
        return
    
    logger.info(f"Processing {len(txt_files)} existing .txt files...")
    
    for file_path in txt_files:
        handler.process_file(str(file_path))


def watch_directory(source_dir, base_destination_dir, order_number, process_existing=True):
    """
    Watch a directory for new .txt files and move them to appropriate folders.
    
    Args:
        source_dir: Directory to watch for new .txt files
        base_destination_dir: Base directory containing ply folders
        order_number: The production order number to match
        process_existing: Whether to process existing files on start
    """
    # Validate directories
    source_path = Path(source_dir)
    dest_path = Path(base_destination_dir)
    
    if not source_path.exists():
        raise ValueError(f"Source directory does not exist: {source_dir}")
    
    if not dest_path.exists():
        raise ValueError(f"Destination directory does not exist: {base_destination_dir}")
    
    # Process existing files if requested
    if process_existing:
        process_existing_files(source_dir, base_destination_dir, order_number)
    
    # Set up file watcher
    event_handler = TextFileHandler(source_dir, base_destination_dir, order_number)
    observer = Observer()
    observer.schedule(event_handler, source_dir, recursive=False)
    
    logger.info("=" * 60)
    logger.info(f"📁 Watching directory: {source_dir}")
    logger.info(f"📂 Destination directory: {base_destination_dir}")
    logger.info(f"🔢 Order number: {order_number}")
    logger.info("Press Ctrl+C to stop watching...")
    logger.info("=" * 60)
    
    try:
        observer.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("Stopping file watcher...")
    
    observer.join()


def move_txt_files_once(source_dir, base_destination_dir, order_number):
    """
    One-time move of .txt files from source directory to matching ply folders.
    
    Args:
        source_dir: Directory containing .txt files
        base_destination_dir: Base directory with ply folders
        order_number: Production order number to match
    """
    source_path = Path(source_dir)
    dest_path = Path(base_destination_dir)
    
    if not source_path.exists():
        logger.error(f"Source directory not found: {source_dir}")
        return False
    
    if not dest_path.exists():
        logger.error(f"Destination directory not found: {base_destination_dir}")
        return False
    
    # Find all .txt files
    txt_files = list(source_path.glob('*.txt'))
    
    if not txt_files:
        logger.info("No .txt files found")
        return True
    
    logger.info(f"Found {len(txt_files)} .txt files")
    
    moved_count = 0
    failed_count = 0
    
    for file_path in txt_files:
        filename = file_path.name
        
        # Extract ply ID from filename
        name = file_path.stem  # Remove extension
        
        # Try to extract ply ID
        match = re.match(r'^([A-Za-z0-9]+)', name)
        if not match:
            logger.warning(f"Could not extract ply ID from: {filename}")
            failed_count += 1
            continue
        
        ply_id = match.group(1)
        
        # Find destination folder
        found_folders = []
        
        # Look for folder containing both ply_id and order_number
        for folder in dest_path.iterdir():
            if folder.is_dir():
                folder_name = folder.name.upper()
                if ply_id.upper() in folder_name and order_number.upper() in folder_name:
                    found_folders.append(folder)
        
        # If not found with order number, try just the ply ID
        if not found_folders:
            for folder in dest_path.iterdir():
                if folder.is_dir() and ply_id.upper() in folder.name.upper():
                    found_folders.append(folder)
        
        if not found_folders:
            logger.warning(f"No destination folder found for ply: {ply_id}")
            failed_count += 1
            continue
        
        # Use the most specific match
        dest_folder = sorted(found_folders, key=lambda x: len(x.name), reverse=True)[0]
        
        # Create destination folder if it doesn't exist
        dest_folder.mkdir(parents=True, exist_ok=True)
        
        dest_path_full = dest_folder / filename
        
        # Move the file
        try:
            if dest_path_full.exists():
                # Rename with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_name = f"{Path(filename).stem}_{timestamp}.txt"
                dest_path_full = dest_folder / new_name
                logger.info(f"File exists, renaming to: {new_name}")
            
            shutil.move(str(file_path), str(dest_path_full))
            moved_count += 1
            logger.info(f"✓ Moved: {filename} -> {dest_folder.name}")
        except Exception as e:
            logger.error(f"Error moving {filename}: {str(e)}")
            failed_count += 1
    
    logger.info("=" * 60)
    logger.info(f"✅ Successfully moved: {moved_count} files")
    logger.info(f"❌ Failed: {failed_count} files")
    logger.info("=" * 60)
    
    return True


# # Django integration helper
# def get_file_paths_from_django():
#     """Get file paths from Django settings."""
#     from django.conf import settings
    
#     # You can add these to your settings.py
#     source_dir = getattr(settings, 'PLY_FILE_SOURCE_DIR', '/tmp/ply_files')
#     dest_dir = getattr(settings, 'PLY_FILE_DEST_DIR', '/media/ply_folders')
#     order_number = getattr(settings, 'CURRENT_ORDER_NUMBER', 'ORD123')
    
#     return source_dir, dest_dir, order_number


        
        
