import os
import re

directory = 'academia/'

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    original = content

    # 1. order_by replacements
    content = content.replace("order_by('apellidos', 'nombres')", "order_by('nombres')")
    content = content.replace("order_by('cierre', 'apellidos', 'nombres')", "order_by('cierre', 'nombres')")
    content = content.replace("order_by('-archivado_en', 'apellidos', 'nombres')", "order_by('-archivado_en', 'nombres')")
    
    # 2. String formatting f"{...nombres} {...apellidos}"
    content = re.sub(r'\{([a-zA-Z0-9_.]+)\.nombres\} \{([a-zA-Z0-9_.]+)\.apellidos\}', r'{\1.nombres}', content)
    
    # 3. f"{...apellidos} {...nombres}"
    content = re.sub(r'\{([a-zA-Z0-9_.]+)\.apellidos\} \{([a-zA-Z0-9_.]+)\.nombres\}', r'{\1.nombres}', content)
    
    # 4. In views_adicional.py Q filters
    content = content.replace("Q(estudiante__apellidos__icontains=q) |", "")
    content = content.replace("Q(persona_externa__apellidos__icontains=q) |", "")
    content = content.replace("Q(apellidos__icontains=q) |", "")

    # 5. Dicts/Tuples assignments
    content = content.replace("'apellidos': request.GET.get('apellidos', ''),", "")
    content = content.replace("'apellidos': est.apellidos,", "")
    content = content.replace("'apellidos': est_arch.apellidos,", "")
    content = content.replace("'apellidos': p.apellidos,", "")
    
    content = content.replace("m.estudiante.apellidos,", "")
    
    content = content.replace("apellidos=a.apellidos,", "")
    content = content.replace("def __init__(self, cedula, apellidos, nombres, pk):", "def __init__(self, cedula, nombres, pk):")
    content = content.replace("self.apellidos = apellidos", "")
    
    # 6. Comma separated lists (tuples/function calls)
    # e.g., e.cedula, e.apellidos, e.nombres -> e.cedula, e.nombres
    content = re.sub(r'([a-zA-Z0-9_]+)\.apellidos, ([a-zA-Z0-9_]+)\.nombres', r'\2.nombres', content)
    
    # In views_cierre.py
    content = content.replace("apellidos=est.apellidos if est else '',", "")
    content = content.replace("apellidos=estudiante.apellidos,", "")

    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Fixed {filepath}")

for root, dirs, files in os.walk(directory):
    if 'migrations' in root or '__pycache__' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))
