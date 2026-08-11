import os
import re
import json
import datetimeimport os
import re
import json
import datetime
import uuid
from django.conf import settings
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .utils.db_queries import fetch_customer_data, fetch_product_details, fetch_kit_elements
from .utils.db_queries import get_db_connection
import ibm_db


def normalize_string(value, max_length=None):
    if value is None:
        return ''
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if max_length is not None and len(value) > max_length:
        return value[:max_length]
    return value


def get_table_columns(table_name):
    """Return the list of column names for a table.

    This first tries SYSCAT.COLUMNS for the current schema, then falls back to
    a simple `SELECT * FROM table WHERE 1=0` to read metadata from the statement.
    """
    conn = None
    try:
        conn = get_db_connection()
        table_name_upper = normalize_string(table_name).upper()

        # Try the catalog first; this is the safest, schema-aware path.
        query = """
            SELECT COLNAME
            FROM SYSCAT.COLUMNS
            WHERE TABNAME = ?
              AND TABSCHEMA = CURRENT SCHEMA
            ORDER BY COLNO
        """
        stmt = ibm_db.prepare(conn, query)
        ibm_db.bind_param(stmt, 1, table_name_upper)
        ibm_db.execute(stmt)

        columns = []
        row = ibm_db.fetch_assoc(stmt)
        while row:
            column_name = row.get('COLNAME') or row.get('colname')
            if not column_name:
                break
            columns.append(column_name.upper())
            row = ibm_db.fetch_assoc(stmt)

        if columns:
            return columns

        # Fallback: describe the table by selecting zero rows.
        fallback_query = f"SELECT * FROM {table_name_upper} WHERE 1=0"
        stmt2 = ibm_db.prepare(conn, fallback_query)
        ibm_db.execute(stmt2)

        num_fields = ibm_db.num_fields(stmt2)
        columns = []
        for index in range(num_fields):
            try:
                field_name = ibm_db.field_name(stmt2, index)
                if field_name:
                    columns.append(field_name.upper())
            except Exception:
                continue

        return columns
    except Exception as exc:
        print(f"Error fetching columns for {table_name}: {exc}")
        return []
    finally:
        if conn is not None:
            try:
                ibm_db.close(conn)
            except Exception:
                pass


def get_table_nullability(table_name):
    """Return a map of {COLUMN_NAME: NULLS} for a table."""
    conn = None
    try:
        conn = get_db_connection()
        query = """
            SELECT COLNAME, NULLS
            FROM SYSCAT.COLUMNS
            WHERE TABNAME = ?
              AND TABSCHEMA = CURRENT SCHEMA
            ORDER BY COLNO
        """
        stmt = ibm_db.prepare(conn, query)
        ibm_db.bind_param(stmt, 1, normalize_string(table_name).upper())
        ibm_db.execute(stmt)

        nullability = {}
        row = ibm_db.fetch_assoc(stmt)
        while row:
            column_name = row.get('COLNAME') or row.get('colname')
            nulls = row.get('NULLS')
            if column_name:
                nullability[column_name.upper()] = nulls
            row = ibm_db.fetch_assoc(stmt)

        return nullability
    except Exception as exc:
        print(f"Error fetching nullability for {table_name}: {exc}")
        return {}
    finally:
        if conn is not None:
            try:
                ibm_db.close(conn)
            except Exception:
                pass


def get_insert_value(field, value):
    """Normalize insert values for SKP_RCP, avoiding NULLs on NOT NULL fields."""
    field_lengths = {
        'COMPANYCODE': 3,
        'PRODUCTIONORDERCODE': 10,
        'PRODUCTIONDEMANDCODE': 10,
        'ITEMTYPECODE': 3,
        'DECOSUBCODE01': 10,
        'DECOSUBCODE02': 10,
        'DECOSUBCODE03': 10,
        'DECOSUBCODE04': 10,
        'DECOSUBCODE05': 10,
        'DECOSUBCODE06': 10,
        'DECOSUBCODE07': 10,
        'DECOSUBCODE08': 10,
        'DECOSUBCODE09': 10,
        'DECOSUBCODE10': 10,
        'CODE': 100,
        'ELEMENTDESC': 100,
        'BOXNUMBER': 50,
        'PALLETNUMBER': 100,
        'PACKINGSEQUENCE': 50,
        'LENGHT1': 10,
        'LENGHT2': 10,
        'WIDTH1': 10,
        'WIDTH2': 10,
        'THICKNESS': 10,
        'ROOTSIDEANGLEA2': 10,
        'TIPSIDEANGLEA1': 10,
        'TIPSIDEANGLEA2': 10,
        'ANGLEB1': 10,
        'ANGLEB2': 10,
        'ROOTSIDEANGLEC1': 10,
        'ROOTSIDEANGLEC2': 10,
        'TIPSIDEANGLEC1': 10,
        'TIPSIDEANGLEC2': 10,
        'T1': 10,
        'T2': 10,
        'CREATIONUSER': 25,
        'CREATIONDATETIME': 26,
        'NETWEIGHT': 100,
        'GROSSWEIGHT': 100,
        'ABSUNIQUEID': 19,
        'BOXSEQUENCE': 100,
        'FBGFABRIC': 100,
        'CUTTYPE': 100,
        'PAPERTUBE': 100,
        'WEIGHTUNITOFMEASURECODE': 100,
        'CODE': 100,
        'PLACEMENTINBOX': 100,
    }
    numeric_fields = {
        'TOTALPCS', 'ELEMENTSEQ', 'BOXSEQUENCE', 'PACKINGSEQUENCE',
        'LENGHT1', 'LENGHT2', 'WIDTH1', 'WIDTH2', 'THICKNESS', 'T1', 'T2',
        'TOLLENGHT1', 'TOLLENGHT2', 'TOLWIDTH1', 'TOLWIDTH2', 'TOLTHICKNESS',
        'TOLROOTSIDEANGLEA2', 'TOLTIPSIDEANGLEA1', 'TOLTIPSIDEANGLEA2',
        'TOLANGLEB1', 'TOLANGLEB2', 'TOLROOTSIDEANGLEC1', 'TOLROOTSIDEANGLEC2',
        'TOLTIPSIDEANGLEC1', 'TOLTIPSIDEANGLEC2', 'TOLT1', 'TOLT2',
        'NETWEIGHT', 'GROSSWEIGHT', 'ABSUNIQUEID'
    }
    datetime_fields = {'CREATIONDATETIME'}

    max_length = field_lengths.get(field, 100)

    if value is None:
        if field in datetime_fields:
            return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if field in numeric_fields:
            return 0
        return ''

    if field in datetime_fields:
        if isinstance(value, str) and not value.strip():
            return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return normalize_string(value, max_length)

    if field in numeric_fields:
        try:
            numeric_value = float(value)
            if field == 'ABSUNIQUEID':
                return int(numeric_value)
            normalized = str(numeric_value)
            return normalize_string(normalized, max_length)
        except (TypeError, ValueError):
            return 0

    return normalize_string(value, max_length)


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
    
    # ========== DO NOT APPLY DEFAULTS FOR MISSING VALUES ==========
    if pressur_bal is None:
        pressur_bal = ''
        print("[EXTRACT] No PRESSURBAL found; leaving blank")

    if pl1 is None:
        pl1 = ''
        print("[EXTRACT] No PL1 found; leaving blank")

    # If no packing_sequence found, use pl1 as fallback only when pl1 is present
    if not packing_sequence and pl1:
        packing_sequence = pl1
    
    print(f"[EXTRACT] FINAL - PressurBal: {pressur_bal}, PL1: {pl1}, PackingSeq: {packing_sequence}\n")
    return pressur_bal, pl1, packing_sequence





def get_element_data(request, element_id):
    """
    Fetch dimensions from SKP_RCP
    Fetch tolerance from SKP_KITUPLOAD
    """

    order_code = request.GET.get("order_code")
    demand_code = request.GET.get("demand_code")
    element_desc = request.GET.get("element_desc") or element_id
    pallet_number = request.GET.get("pallet_number", "")
    box_number = request.GET.get("box_number", "")

    conn = None

    try:
        conn = get_db_connection()

        # ------------------ RCP DATA ------------------

        rcp_table = get_rcp_table_name()
        rcp_sql = f"""
        SELECT
            LENGHT1,
            LENGHT2,
            WIDTH1,
            WIDTH2,
            THICKNESS,
            ROOTSIDEANGLEA2,
            TIPSIDEANGLEA1,
            TIPSIDEANGLEA2,
            ANGLEB1,
            ANGLEB2,
            ROOTSIDEANGLEC1,
            ROOTSIDEANGLEC2,
            TIPSIDEANGLEC1,
            TIPSIDEANGLEC2,
            T1,
            T2
        FROM {rcp_table}
        WHERE ELEMENTDESC=?
        """

        stmt = ibm_db.prepare(conn, rcp_sql)
        ibm_db.bind_param(stmt, 1, element_desc)
        ibm_db.execute(stmt)

        rcp_row = ibm_db.fetch_assoc(stmt)

        if not rcp_row:
            rcp_row = {}

        element_data = {}

        fields = [
            "LENGHT1",
            "LENGHT2",
            "WIDTH1",
            "WIDTH2",
            "THICKNESS",
            "ROOTSIDEANGLEA2",
            "TIPSIDEANGLEA1",
            "TIPSIDEANGLEA2",
            "ANGLEB1",
            "ANGLEB2",
            "ROOTSIDEANGLEC1",
            "ROOTSIDEANGLEC2",
            "TIPSIDEANGLEC1",
            "TIPSIDEANGLEC2",
            "T1",
            "T2"
        ]

        for field in fields:
            value = rcp_row.get(field)

            if value is None:
                value = rcp_row.get(field.upper())

            if isinstance(value, str):
                value = value.strip()

            element_data[field] = value

        # ------------------ KITUPLOAD TOLERANCE ------------------

        kitupload_sql = """
        SELECT
            LENGHT1,
            LENGHT2,
            WIDTH1,
            WIDTH2,
            THICKNESS,
            ROOTSIDEANGLEA2,
            TIPSIDEANGLEA1,
            TIPSIDEANGLEA2,
            ANGLEB1,
            ANGLEB2,
            ROOTSIDEANGLEC1,
            ROOTSIDEANGLEC2,
            TIPSIDEANGLEC1,
            TIPSIDEANGLEC2,
            T1,
            T2,
            TOLLENGHT1,
            TOLLENGHT2,
            TOLWIDTH1,
            TOLWIDTH2,
            TOLTHICKNESS,
            TOLROOTSIDEANGLEA2,
            TOLTIPSIDEANGLEA1,
            TOLTIPSIDEANGLEA2,
            TOLANGLEB1,
            TOLANGLEB2,
            TOLROOTSIDEANGLEC1,
            TOLROOTSIDEANGLEC2,
            TOLTIPSIDEANGLEC1,
            TOLTIPSIDEANGLEC2,
            TOLT1,
            TOLT2
        FROM SKP_KITUPLOAD
        WHERE ELEMENTDESC = ?
        """

        stmt2 = ibm_db.prepare(conn, kitupload_sql)
        ibm_db.bind_param(stmt2, 1, normalize_string(element_desc, 100))
        ibm_db.execute(stmt2)

        tol_row = ibm_db.fetch_assoc(stmt2)

        tolerance_data = {}
        baseline_data = {}

        baseline_fields = [
            "LENGHT1",
            "LENGHT2",
            "WIDTH1",
            "WIDTH2",
            "THICKNESS",
            "ROOTSIDEANGLEA2",
            "TIPSIDEANGLEA1",
            "TIPSIDEANGLEA2",
            "ANGLEB1",
            "ANGLEB2",
            "ROOTSIDEANGLEC1",
            "ROOTSIDEANGLEC2",
            "TIPSIDEANGLEC1",
            "TIPSIDEANGLEC2",
            "T1",
            "T2"
        ]

        tol_fields = [
            "TOLLENGHT1",
            "TOLLENGHT2",
            "TOLWIDTH1",
            "TOLWIDTH2",
            "TOLTHICKNESS",
            "TOLROOTSIDEANGLEA2",
            "TOLTIPSIDEANGLEA1",
            "TOLTIPSIDEANGLEA2",
            "TOLANGLEB1",
            "TOLANGLEB2",
            "TOLROOTSIDEANGLEC1",
            "TOLROOTSIDEANGLEC2",
            "TOLTIPSIDEANGLEC1",
            "TOLTIPSIDEANGLEC2",
            "TOLT1",
            "TOLT2"
        ]

        if tol_row:
            for field in baseline_fields:
                value = tol_row.get(field)
                if value is None:
                    value = tol_row.get(field.upper())
                if isinstance(value, str):
                    value = value.strip()
                baseline_data[field] = value

            for field in tol_fields:
                value = tol_row.get(field)
                if value is None:
                    value = tol_row.get(field.upper())
                if isinstance(value, str):
                    value = value.strip()
                tolerance_data[field] = value
                

        return JsonResponse({
            "status": "success",
            "element_data": element_data,
            "baseline_data": baseline_data,
            "tolerance_data": tolerance_data,
        })

    except Exception as e:

        print(e)

        return JsonResponse({

            "status": "error",

            "message": str(e)

        })

    finally:

        if conn:

            ibm_db.close(conn)

# def get_element_data(request, element_id):
#     """Fetch element data from SKP_RCP table"""

#     order_code = request.GET.get('order_code')
#     demand_code = request.GET.get('demand_code')
#     element_desc = request.GET.get('element_desc') or element_id

#     conn = None
#     try:
#         conn = get_db_connection()

#         sql = """
#             SELECT
#                 LENGHT1,
#                 LENGHT2,
#                 WIDTH1,
#                 WIDTH2,
#                 THICKNESS,
#                 ROOTSIDEANGLEA2,
#                 TIPSIDEANGLEA1,
#                 TIPSIDEANGLEA2,
#                 ANGLEB1,
#                 ANGLEB2,
#                 ROOTSIDEANGLEC1,
#                 ROOTSIDEANGLEC2,
#                 TIPSIDEANGLEC1,
#                 TIPSIDEANGLEC2,
#                 T1,
#                 T2
#             FROM SKP_RCP
#             WHERE ELEMENTDESC = ?
#         """

#         stmt = ibm_db.prepare(conn, sql)
#         ibm_db.bind_param(stmt, 1, element_desc)
#         ibm_db.execute(stmt)

#         row = ibm_db.fetch_assoc(stmt)

#         if not row:
#             return JsonResponse({
#                 "status": "error",
#                 "message": "No data found in SKP_RCP"
#             })

#         element_data = {
#             "LENGHT1": row.get("LENGHT1"),
#             "LENGHT2": row.get("LENGHT2"),
#             "WIDTH1": row.get("WIDTH1"),
#             "WIDTH2": row.get("WIDTH2"),
#             "THICKNESS": row.get("THICKNESS"),
#             "ROOTSIDEANGLEA2": row.get("ROOTSIDEANGLEA2"),
#             "TIPSIDEANGLEA1": row.get("TIPSIDEANGLEA1"),
#             "TIPSIDEANGLEA2": row.get("TIPSIDEANGLEA2"),
#             "ANGLEB1": row.get("ANGLEB1"),
#             "ANGLEB2": row.get("ANGLEB2"),
#             "ROOTSIDEANGLEC1": row.get("ROOTSIDEANGLEC1"),
#             "ROOTSIDEANGLEC2": row.get("ROOTSIDEANGLEC2"),
#             "TIPSIDEANGLEC1": row.get("TIPSIDEANGLEC1"),
#             "TIPSIDEANGLEC2": row.get("TIPSIDEANGLEC2"),
#             "T1": row.get("T1"),
#             "T2": row.get("T2"),
#         }

#         return JsonResponse({
#             "status": "success",
#             "element_data": element_data
#         })

#     except Exception as e:
#         return JsonResponse({
#             "status": "error",
#             "message": str(e)
#         })

#     finally:
#         if conn:
#             ibm_db.close(conn)



# ---------------------- SAVE ELEMENT DIMENSIONS (NEW) ----------------------
def fetch_kitupload_baseline_data(element_desc, order_code, demand_code, pallet_number, box_number):
    """Fetch baseline values from SKP_KITUPLOAD for an element."""
    conn = None
    try:
        conn = get_db_connection()
        query = """
            SELECT
                LENGHT1, LENGHT2, WIDTH1, WIDTH2, THICKNESS,
                ROOTSIDEANGLEA2, TIPSIDEANGLEA1, TIPSIDEANGLEA2,
                ANGLEB1, ANGLEB2, ROOTSIDEANGLEC1, ROOTSIDEANGLEC2,
                TIPSIDEANGLEC1, TIPSIDEANGLEC2, T1, T2
            FROM SKP_KITUPLOAD
            WHERE ELEMENTDESC = ?
              AND PALLETNUMBER = ?
              AND BOXNUMBER = ?
        """
        stmt = ibm_db.prepare(conn, query)
        ibm_db.bind_param(stmt, 1, normalize_string(element_desc, 100))
        ibm_db.bind_param(stmt, 2, normalize_string(pallet_number or '', 100))
        ibm_db.bind_param(stmt, 3, normalize_string(box_number or '', 50))
        ibm_db.execute(stmt)

        row = ibm_db.fetch_assoc(stmt)
        if not row:
            return None

        baseline_data = {}
        fields = [
            'LENGHT1', 'LENGHT2', 'WIDTH1', 'WIDTH2', 'THICKNESS',
            'ROOTSIDEANGLEA2', 'TIPSIDEANGLEA1', 'TIPSIDEANGLEA2',
            'ANGLEB1', 'ANGLEB2', 'ROOTSIDEANGLEC1', 'ROOTSIDEANGLEC2',
            'TIPSIDEANGLEC1', 'TIPSIDEANGLEC2', 'T1', 'T2'
        ]

        for field in fields:
            value = row.get(field)
            if value is None:
                value = row.get(field.upper())
            if value is None:
                value = row.get(field.lower())
            if value is not None and isinstance(value, str) and value.strip() == '':
                value = None
            baseline_data[field] = value

        return baseline_data
    except Exception as exc:
        print(f"Error fetching RCP baseline data: {exc}")
        return None
    finally:
        if conn is not None:
            try:
                ibm_db.close(conn)
            except Exception:
                pass






def fetch_kitupload_tolerance_data(element_desc, order_code, demand_code, pallet_number, box_number):
    """Fetch tolerance values from SKP_KITUPLOAD for an element."""
    conn = None
    try:
        conn = get_db_connection()
        query = """
            SELECT
                TOLLENGHT1, TOLLENGHT2, TOLWIDTH1, TOLWIDTH2, TOLTHICKNESS,
                TOLROOTSIDEANGLEA2, TOLTIPSIDEANGLEA1, TOLTIPSIDEANGLEA2,
                TOLANGLEB1, TOLANGLEB2, TOLROOTSIDEANGLEC1, TOLROOTSIDEANGLEC2,
                TOLTIPSIDEANGLEC1, TOLTIPSIDEANGLEC2, TOLT1, TOLT2
            FROM SKP_KITUPLOAD
            WHERE ELEMENTDESC = ?
              AND PALLETNUMBER = ?
              AND BOXNUMBER = ?
        """
        stmt = ibm_db.prepare(conn, query)
        ibm_db.bind_param(stmt, 1, normalize_string(element_desc, 100))
        ibm_db.bind_param(stmt, 2, normalize_string(pallet_number or '', 100))
        ibm_db.bind_param(stmt, 3, normalize_string(box_number or '', 50))
        ibm_db.execute(stmt)

        row = ibm_db.fetch_assoc(stmt)
        if not row:
            return None

        tolerance_data = {}
        fields = [
            'TOLLENGHT1', 'TOLLENGHT2', 'TOLWIDTH1', 'TOLWIDTH2', 'TOLTHICKNESS',
            'TOLROOTSIDEANGLEA2', 'TOLTIPSIDEANGLEA1', 'TOLTIPSIDEANGLEA2',
            'TOLANGLEB1', 'TOLANGLEB2', 'TOLROOTSIDEANGLEC1', 'TOLROOTSIDEANGLEC2',
            'TOLTIPSIDEANGLEC1', 'TOLTIPSIDEANGLEC2', 'TOLT1', 'TOLT2'
        ]

        for field in fields:
            value = row.get(field)
            if value is None:
                value = row.get(field.upper())
            if value is None:
                value = row.get(field.lower())
            if value is not None and isinstance(value, str) and value.strip() == '':
                value = None
            tolerance_data[field] = value

        return tolerance_data
    except Exception as exc:
        print(f"Error fetching KITUPLOAD tolerance data: {exc}")
        return None
    finally:
        if conn is not None:
            try:
                ibm_db.close(conn)
            except Exception:
                pass


def fetch_kitupload_full_row(element_desc, pallet_number=None, box_number=None):
    """Fetch the full non-tolerance row from SKP_KITUPLOAD for an element."""
    conn = None
    try:
        conn = get_db_connection()
        columns = [
            'COMPANYCODE', 'PARTDESC', 'TOTALPCS', 'ITEMTYPECODE',
            'DECOSUBCODE01', 'DECOSUBCODE02', 'DECOSUBCODE03', 'DECOSUBCODE04',
            'DECOSUBCODE05', 'DECOSUBCODE06', 'DECOSUBCODE07', 'DECOSUBCODE08',
            'DECOSUBCODE09', 'DECOSUBCODE10', 'CODE', 'ELEMENTDESC', 'BOXNUMBER',
            'ELEMENTSEQ', 'FBGFABRIC', 'CUTTYPE', 'PALLETNUMBER', 'PAPERTUBE',
            'WEIGHTUNITOFMEASURECODE', 'NETWEIGHT', 'GROSSWEIGHT', 'CREATIONDATETIME',
            'CREATIONUSER', 'ABSUNIQUEID', 'BOXSEQUENCE', 'PACKINGSEQUENCE',
            'PLACEMENTINBOX', 'LENGHT1', 'LENGHT2', 'WIDTH1', 'WIDTH2', 'THICKNESS',
            'ROOTSIDEANGLEA2', 'TIPSIDEANGLEA1', 'TIPSIDEANGLEA2', 'ANGLEB1', 'ANGLEB2',
            'ROOTSIDEANGLEC1', 'ROOTSIDEANGLEC2', 'TIPSIDEANGLEC1', 'TIPSIDEANGLEC2', 'T1', 'T2'
        ]
        query = f"""
            SELECT {', '.join(columns)}
            FROM SKP_KITUPLOAD
            WHERE ELEMENTDESC = ?
              AND PALLETNUMBER = ?
              AND BOXNUMBER = ?
        """
        stmt = ibm_db.prepare(conn, query)
        ibm_db.bind_param(stmt, 1, normalize_string(element_desc, 100))
        ibm_db.bind_param(stmt, 2, normalize_string(pallet_number or '', 100))
        ibm_db.bind_param(stmt, 3, normalize_string(box_number or '', 50))
        ibm_db.execute(stmt)

        row = ibm_db.fetch_assoc(stmt)
        if not row:
            return None

        data = {}
        for field in columns:
            value = row.get(field)
            if value is None:
                value = row.get(field.upper())
            if value is None:
                value = row.get(field.lower())
            if value is not None and isinstance(value, str) and value.strip() == '':
                value = None
            data[field] = value
        return data
    except Exception as exc:
        print(f"Error fetching KITUPLOAD full row: {exc}")
        return None
    finally:
        if conn is not None:
            try:
                ibm_db.close(conn)
            except Exception:
                pass


def get_rcp_table_name():
    """Resolve the RCP table name to use for reads and writes."""
    preferred_tables = ['SKP_RCP', 'KIT_RCP']
    for table_name in preferred_tables:
        conn = None
        try:
            conn = get_db_connection()
            query = f"SELECT 1 FROM {table_name} WHERE 1 = 0"
            stmt = ibm_db.prepare(conn, query)
            ibm_db.execute(stmt)
            return table_name
        except Exception:
            continue
        finally:
            if conn is not None:
                try:
                    ibm_db.close(conn)
                except Exception:
                    pass
    return 'SKP_RCP'


def rcp_row_exists(element_desc):
    """Check whether an RCP row already exists for the element."""
    table_name = get_rcp_table_name()
    conn = None
    try:
        conn = get_db_connection()
        query = f"SELECT 1 FROM {table_name} WHERE ELEMENTDESC = ?"
        stmt = ibm_db.prepare(conn, query)
        ibm_db.bind_param(stmt, 1, normalize_string(element_desc, 100))
        ibm_db.execute(stmt)
        row = ibm_db.fetch_assoc(stmt)
        return row is not None
    except Exception as exc:
        print(f"Error checking RCP row existence: {exc}")
        return False
    finally:
        if conn is not None:
            try:
                ibm_db.close(conn)
            except Exception:
                pass


def save_element_dimensions(request):
    """Save dimension values to SKP_RCP table"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'})
    
    try:
        data = json.loads(request.body)
        element_id = data.get('element_id')
        element_desc = data.get('element_desc') or element_id
        order_code = data.get('order_code')
        demand_code = data.get('demand_code')
        pallet_number = data.get('pallet_number')
        box_number = data.get('box_number')
        dimensions = data.get('dimensions', {})
        
        if not element_desc or not order_code or not demand_code:
            return JsonResponse({'status': 'error', 'message': 'Missing required fields'})
        
        if not dimensions:
            return JsonResponse({'status': 'error', 'message': 'No dimensions to save'})

        baseline_data = fetch_kitupload_baseline_data(element_desc, order_code, demand_code, pallet_number, box_number) or {}
        tolerance_data = fetch_kitupload_tolerance_data(element_desc, order_code, demand_code, pallet_number, box_number) or {}
        full_row = fetch_kitupload_full_row(element_desc, pallet_number, box_number) or {}

        allowed_columns = [
            'LENGHT1', 'LENGHT2', 'WIDTH1', 'WIDTH2', 'THICKNESS',
            'ROOTSIDEANGLEA2', 'TIPSIDEANGLEA1', 'TIPSIDEANGLEA2',
            'ANGLEB1', 'ANGLEB2', 'ROOTSIDEANGLEC1', 'ROOTSIDEANGLEC2',
            'TIPSIDEANGLEC1', 'TIPSIDEANGLEC2', 'T1', 'T2'
        ]
        tolerance_columns = [
            'TOLLENGHT1', 'TOLLENGHT2', 'TOLWIDTH1', 'TOLWIDTH2', 'TOLTHICKNESS',
            'TOLROOTSIDEANGLEA2', 'TOLTIPSIDEANGLEA1', 'TOLTIPSIDEANGLEA2',
            'TOLANGLEB1', 'TOLANGLEB2', 'TOLROOTSIDEANGLEC1', 'TOLROOTSIDEANGLEC2',
            'TOLTIPSIDEANGLEC1', 'TOLTIPSIDEANGLEC2', 'TOLT1', 'TOLT2'
        ]
        insert_columns_list = [
            'COMPANYCODE', 'PRODUCTIONORDERCODE', 'PRODUCTIONDEMANDCODE', 'ITEMTYPECODE',
            'DECOSUBCODE01', 'DECOSUBCODE02', 'DECOSUBCODE03', 'DECOSUBCODE04',
            'DECOSUBCODE05', 'DECOSUBCODE06', 'DECOSUBCODE07', 'DECOSUBCODE08',
            'DECOSUBCODE09', 'DECOSUBCODE10', 'CODE', 'ELEMENTDESC', 'BOXNUMBER',
            'ELEMENTSEQ', 'FBGFABRIC', 'CUTTYPE', 'PALLETNUMBER', 'PAPERTUBE',
            'WEIGHTUNITOFMEASURECODE', 'NETWEIGHT', 'GROSSWEIGHT', 'CREATIONDATETIME',
            'CREATIONUSER', 'ABSUNIQUEID', 'BOXSEQUENCE', 'PACKINGSEQUENCE',
            'PLACEMENTINBOX', 'LENGHT1', 'LENGHT2', 'WIDTH1', 'WIDTH2', 'THICKNESS',
            'ROOTSIDEANGLEA2', 'TIPSIDEANGLEA1', 'TIPSIDEANGLEA2', 'ANGLEB1', 'ANGLEB2',
            'ROOTSIDEANGLEC1', 'ROOTSIDEANGLEC2', 'TIPSIDEANGLEC1', 'TIPSIDEANGLEC2', 'T1', 'T2'
        ] + tolerance_columns

        def resolve_insert_value(field):
            if field == 'ELEMENTDESC':
                return element_desc
            if field == 'PRODUCTIONORDERCODE':
                return order_code
            if field == 'PRODUCTIONDEMANDCODE':
                return demand_code
            if field == 'BOXNUMBER':
                return box_number
            if field == 'PALLETNUMBER':
                return pallet_number
            if field in tolerance_columns:
                source_field = field.replace('TOL', '')
                if source_field in dimensions:
                    return dimensions[source_field]
                value = tolerance_data.get(field)
                if value is not None:
                    return value
                return full_row.get(field)
            if field in dimensions and field in allowed_columns:
                return dimensions[field]
            if field in full_row:
                return full_row.get(field)
            if field in baseline_data:
                return baseline_data[field]
            return None

        table_name = get_rcp_table_name()
        table_columns = get_table_columns(table_name)
        table_nullability = get_table_nullability(table_name)
        if not table_columns:
            table_columns = {
                'ELEMENTDESC', 'BOXNUMBER', 'PALLETNUMBER', 'ELEMENTSEQ', 'PACKINGSEQUENCE'
            } | set(allowed_columns) | set(tolerance_columns)
        else:
            table_columns = set(table_columns)

        not_null_columns = {
            col for col, nulls in table_nullability.items() if nulls == 'N'
        }
        not_null_columns |= {
            'COMPANYCODE', 'PRODUCTIONORDERCODE', 'PRODUCTIONDEMANDCODE',
            'ITEMTYPECODE', 'ABSUNIQUEID'
        }

        def build_insert_values():
            insert_columns = []
            insert_values = []
            for field in sorted(table_columns):
                if field not in insert_columns_list and field not in not_null_columns:
                    continue

                value = resolve_insert_value(field)
                if value is None and field not in not_null_columns:
                    continue

                insert_columns.append(field)
                insert_values.append(get_insert_value(field, value))

            return insert_columns, insert_values

        update_columns = []
        update_values = []

        for field in allowed_columns:
            if field not in dimensions:
                continue

            raw_value = dimensions[field]
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                return JsonResponse({'status': 'error', 'message': f'Invalid numeric value for {field}'})

            baseline = baseline_data.get(field)
            tolerance_key = f'TOL{field}'
            tolerance = tolerance_data.get(tolerance_key)

            if baseline is not None and tolerance is not None:
                try:
                    baseline_value = float(baseline)
                    tolerance_value = float(tolerance)
                except (TypeError, ValueError):
                    return JsonResponse({'status': 'error', 'message': f'Invalid baseline/tolerance for {field}'})

                min_allowed = baseline_value - tolerance_value
                max_allowed = baseline_value + tolerance_value
                if value < min_allowed or value > max_allowed:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'{field} value {value} is outside allowed range {min_allowed} - {max_allowed}'
                    })

            update_columns.append(f"{field} = ?")
            update_values.append(normalize_string(raw_value, 10))
            tol_field = f'TOL{field}'
            if tol_field in table_columns:
                update_columns.append(f"{tol_field} = ?")
                update_values.append(normalize_string(raw_value, 10))

        if not update_columns:
            return JsonResponse({'status': 'error', 'message': 'No valid dimension fields found'})

        conn = get_db_connection()
        try:
            existing_row = rcp_row_exists(element_desc)
        except Exception:
            existing_row = True

        if existing_row:
            query = f"""
                UPDATE {table_name}
                SET {', '.join(update_columns)}
                WHERE ELEMENTDESC = ?
            """
            update_values.append(normalize_string(element_desc, 100))
        else:
            insert_columns = []
            insert_values = []
            required_not_null = {
                'COMPANYCODE', 'PRODUCTIONORDERCODE', 'PRODUCTIONDEMANDCODE',
                'ITEMTYPECODE', 'ABSUNIQUEID'
            }
            for field in insert_columns_list:
                if field not in table_columns:
                    continue

                value = resolve_insert_value(field)
                if value is None and field not in required_not_null:
                    continue

                insert_columns.append(field)
                insert_values.append(get_insert_value(field, value))

            query = f"""
                INSERT INTO {table_name} ({', '.join(insert_columns)})
                VALUES ({', '.join(['?'] * len(insert_columns))})
            """
            update_values = insert_values

        stmt = ibm_db.prepare(conn, query)

        for index, value in enumerate(update_values, start=1):
            ibm_db.bind_param(stmt, index, value)

        ibm_db.execute(stmt)
        rows_updated = None
        try:
            if hasattr(ibm_db, 'num_rows'):
                rows_updated = ibm_db.num_rows(stmt)
        except Exception as num_exc:
            print(f"Row count warning: {num_exc}")

        if existing_row and rows_updated == 0:
            print(f"No existing row updated for ELEMENTDESC={element_desc}; inserting instead.")
            insert_columns, insert_values = build_insert_values()

            insert_query = f"""
                INSERT INTO {table_name} ({', '.join(insert_columns)})
                VALUES ({', '.join(['?'] * len(insert_columns))})
            """
            stmt = ibm_db.prepare(conn, insert_query)
            for index, value in enumerate(insert_values, start=1):
                ibm_db.bind_param(stmt, index, value)
            ibm_db.execute(stmt)

        try:
            if hasattr(ibm_db, 'commit'):
                ibm_db.commit(conn)
        except Exception as commit_exc:
            print(f"Commit warning: {commit_exc}")
        try:
            ibm_db.close(conn)
        except Exception as close_exc:
            print(f"Close warning: {close_exc}")

        print(f"Dimensions inserted into SKP_RCP for element {element_id}: {dimensions}")

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

        
        
        # Process each element's human image separately
        for element in kit_elements:
            current_ply = element.get('ELEMENTDESC', '').strip()
            
            

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

        return render(request, 'view_data.html', context)

    return render(request, 'fetch_data.html')
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
