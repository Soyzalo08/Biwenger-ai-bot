import re
import os
import sys

# Secuencias ANSI para colores en consola
RESET = "\033[0m"
BOLD = "\033[1m"
UNDERLINE = "\033[4m"

# Colores de texto
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

# Colores de fondo
BG_CYAN = "\033[46m"
BG_BLACK = "\033[40m"

def init_terminal():
    """
    Inicializa el soporte de colores ANSI en Windows si es necesario.
    """
    if os.name == 'nt':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # Habilitar el procesamiento virtual de terminal
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            # Si falla, simplemente los colores podrían no renderizarse en cmd antiguos,
            # pero no detendrá la ejecución
            pass

class RecommenderPresenter:
    def __init__(self):
        init_terminal()

    def present(self, analysis_text):
        """
        Formatea e imprime de manera espectacular el análisis markdown en consola.
        """
        lines = analysis_text.split("\n")
        formatted_lines = []
        
        in_table = False
        
        for line in lines:
            # Cabeceras principales con iconos o números
            is_main_header = (
                line.startswith("# ") or 
                re.match(r"^#+\s", line) or
                re.match(r"^\d+\.\s", line) or
                any(icon in line for icon in ["🚀", "⚠️", "⚽", "📊", "🏆"])
            )
            
            if is_main_header:
                formatted_lines.append(f"\n{BOLD}{CYAN}{'=' * len(line.strip())}")
                formatted_lines.append(f"{BOLD}{CYAN}{line.strip()}{RESET}")
                formatted_lines.append(f"{BOLD}{CYAN}{'=' * len(line.strip())}{RESET}")
                in_table = False
                
            elif line.startswith("## ") or line.startswith("### "):
                formatted_lines.append(f"\n{BOLD}{YELLOW}{line.strip()}{RESET}")
                in_table = False
                
            elif "|" in line:
                # Estamos procesando una tabla markdown
                in_table = True
                
                # Cabecera de la tabla
                if any(h in line.lower() for h in ["jugador", "posición", "precio", "acción", "estado", "rol"]):
                    formatted_lines.append(f"{BOLD}{BLUE}{line}{RESET}")
                # Separador de cabecera
                elif "---" in line:
                    formatted_lines.append(f"{BLUE}{line}{RESET}")
                else:
                    # Fila de datos normales de la tabla
                    colored_row = line
                    
                    # Coloreamos palabras clave estratégicas
                    # Compras / Especulaciones en verde
                    colored_row = re.sub(
                        r"\b(Comprar|Fichar|Especular|Alinear|Sí|Titular|Subiendo|Subida)\b", 
                        f"{GREEN}\\1{RESET}", 
                        colored_row, 
                        flags=re.IGNORECASE
                    )
                    # Ventas / Lesiones en rojo
                    colored_row = re.sub(
                        r"\b(Vender|Venta|Lesionado|Lesión|Baja|Suplente|Bajando|Duda)\b", 
                        f"{RED}\\1{RESET}", 
                        colored_row, 
                        flags=re.IGNORECASE
                    )
                    # Estados estables u Ok en amarillo/azul
                    colored_row = re.sub(
                        r"\b(Ok|Estable|Mantener|Doubtful|No Cambiar)\b", 
                        f"{YELLOW}\\1{RESET}", 
                        colored_row, 
                        flags=re.IGNORECASE
                    )
                    
                    # Resaltar nombres de jugadores entre | |
                    # Buscamos la primera celda y la ponemos en negrita
                    parts = colored_row.split("|")
                    if len(parts) > 2:
                        parts[1] = f"{BOLD}{WHITE}{parts[1]}{RESET}"
                        colored_row = "|".join(parts)
                        
                    formatted_lines.append(colored_row)
            else:
                if in_table and not line.strip():
                    # Fin de la tabla
                    in_table = False
                formatted_lines.append(line)
                
        # Imprimir contenedor principal usando caracteres ASCII estándar para máxima compatibilidad
        print("\n" + "+" + "=" * 78 + "+")
        print(f"|{BOLD}{MAGENTA}{'ANÁLISIS ESTRATÉGICO Y RECOMENDACIONES DE BIWENGER 2026'.center(78)}{RESET}|")
        print("+" + "=" * 78 + "+")
        
        # En Windows a veces los emoticonos u otros caracteres unicode de la respuesta de Gemini también
        # pueden causar UnicodeEncodeError si la consola está en un formato cp1252 heredado.
        # Filtramos la impresión de cada línea de forma segura.
        encoding = sys.stdout.encoding or 'utf-8'
        safe_output = []
        for line in formatted_lines:
            try:
                line.encode(encoding)
                safe_output.append(line)
            except UnicodeEncodeError:
                # Si hay caracteres no admitidos, los reemplazamos por el carácter de sustitución "?"
                encoded = line.encode(encoding, errors='replace')
                safe_output.append(encoded.decode(encoding))

        print("\n".join(safe_output))
        
        print("\n" + "+" + "=" * 78 + "+")
        print(f"|{BOLD}{GREEN}{'¡Mucha suerte en tu jornada del Mundial!'.center(78)}{RESET}|")
        print("+" + "=" * 78 + "+\n")
