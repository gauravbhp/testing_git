import os
import re
import json
import datetime
from django.conf import settings
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .utils.db_queries import fetch_customer_data, fetch_product_details, fetch_kit_elements
from .utils.db_queries import get_db_connection


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


# ---------------------- FETCH ELEMENT DATA (NEW) ----------------------
def get_element_data(request, element_id):
    """Fetch element data and tolerance data from SKP_KITUPLOAD table"""
    order_code = request.GET.get('order_code')
    demand_code = request.GET.get('demand_code')
    
    if not order_code or not demand_code:
        return JsonResponse({'status': 'error', 'message': 'Missing order or demand code'})
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch element data
            cursor.execute("""
                SELECT 
                    LENGHT1, LENGHT2, WIDTH1, WIDTH2, THICKNESS,
                    ROOTSIDEANGLEA2, TIPSIDEANGLEA1, TIPSIDEANGLEA2,
                    ANGLEB1, ANGLEB2, ROOTSIDEANGLEC1, ROOTSIDEANGLEC2,
                    TIPSIDEANGLEC1, TIPSIDEANGLEC2, T1, T2,
                    TOLLENGHT1, TOLLENGHT2, TOLWIDTH1, TOLWIDTH2, TOLTHICKNESS,
                    TOLROOTSIDEANGLEA2, TOLTIPSIDEANGLEA1, TOLTIPSIDEANGLEA2,
                    TOLANGLEB1, TOLANGLEB2, TOLROOTSIDEANGLEC1, TOLROOTSIDEANGLEC2,
                    TOLTIPSIDEANGLEC1, TOLTIPSIDEANGLEC2, TOLT1, TOLT2
                FROM SKP_KITUPLOAD 
                WHERE ELEMENTID = ? 
                AND PRODUCTIONORDERCODE = ? 
                AND PRODUCTIONDEMANDCODE = ?
            """, [element_id, order_code, demand_code])
            
            row = cursor.fetchone()
            cursor.close()
            
            if not row:
                return JsonResponse({'status': 'error', 'message': 'Element not found'})
            
            # Map column names to values
            columns = [
                'LENGHT1', 'LENGHT2', 'WIDTH1', 'WIDTH2', 'THICKNESS',
                'ROOTSIDEANGLEA2', 'TIPSIDEANGLEA1', 'TIPSIDEANGLEA2',
                'ANGLEB1', 'ANGLEB2', 'ROOTSIDEANGLEC1', 'ROOTSIDEANGLEC2',
                'TIPSIDEANGLEC1', 'TIPSIDEANGLEC2', 'T1', 'T2',
                'TOLLENGHT1', 'TOLLENGHT2', 'TOLWIDTH1', 'TOLWIDTH2', 'TOLTHICKNESS',
                'TOLROOTSIDEANGLEA2', 'TOLTIPSIDEANGLEA1', 'TOLTIPSIDEANGLEA2',
                'TOLANGLEB1', 'TOLANGLEB2', 'TOLROOTSIDEANGLEC1', 'TOLROOTSIDEANGLEC2',
                'TOLTIPSIDEANGLEC1', 'TOLTIPSIDEANGLEC2', 'TOLT1', 'TOLT2'
            ]
            
            element_data = {}
            tolerance_data = {}
            
            # Convert tuple to list for indexing
            row_list = list(row)
            
            for i, col in enumerate(columns):
                if i < 16:  # First 16 are element data
                    element_data[col] = row_list[i]
                else:  # Last 16 are tolerance data
                    tolerance_data[col] = row_list[i]
            
            return JsonResponse({
                'status': 'success',
                'element_data': element_data,
                'tolerance_data': tolerance_data
            })
            
    except Exception as e:
        print(f"Error fetching element data: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)})


# ---------------------- SAVE ELEMENT DIMENSIONS (NEW) ----------------------
@csrf_exempt
def save_element_dimensions(request):
    """Save dimension values to SKP_KITUPLOAD table"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'})
    
    try:
        data = json.loads(request.body)
        element_id = data.get('element_id')
        order_code = data.get('order_code')
        demand_code = data.get('demand_code')
        pallet_number = data.get('pallet_number')
        box_number = data.get('box_number')
        dimensions = data.get('dimensions', {})
        
        if not element_id or not order_code or not demand_code:
            return JsonResponse({'status': 'error', 'message': 'Missing required fields'})
        
        if not dimensions:
            return JsonResponse({'status': 'error', 'message': 'No dimensions to update'})
        
        # Build update query dynamically
        update_fields = []
        params = []
        
        for field, value in dimensions.items():
            update_fields.append(f"{field} = ?")
            params.append(value)
        
        # Add parameters for WHERE clause
        params.extend([element_id, order_code, demand_code])
        
        query = f"""
            UPDATE SKP_KITUPLOAD 
            SET {', '.join(update_fields)}
            WHERE ELEMENTID = ? 
            AND PRODUCTIONORDERCODE = ? 
            AND PRODUCTIONDEMANDCODE = ?
        """
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            cursor.close()
        
        print(f"Dimensions updated for element {element_id}: {dimensions}")
        
        return JsonResponse({'status': 'success', 'message': 'Dimensions saved successfully'})
        
    except Exception as e:
        print(f"Error saving dimensions: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)})


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
