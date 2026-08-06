import os
import time
import random
import socket
from urllib.parse import urlparse
from datetime import datetime, date
from decimal import Decimal

from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors as pg_errors

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB límite subida


def get_db():
    """
    Establece conexión con PostgreSQL.
    Prioriza DATABASE_URL (Producción) y hace fallback a local (Docker).
    """
    db_url = os.environ.get('DATABASE_URL')
    
    # Configuración base
    config_base = {
        'cursor_factory': RealDictCursor,
        'connect_timeout': 5
    }

    # 1. Intento con DATABASE_URL (Render, Heroku, Railway, etc.)
    if db_url:
        u = urlparse(db_url)
        host = u.hostname
        port = u.port or 5432
        dbname = (u.path or '').lstrip('/')
        
        # Resolución IPv4 explícita para evitar timeouts en DNS de algunos proveedores
        ip4 = None
        try:
            infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            if infos: 
                ip4 = infos[0][4][0]
        except Exception:
            pass

        estrategias = []
        if ip4:
            # Estrategia 1: Host + Hostaddr (Máxima compatibilidad)
            estrategias.append(dict(host=host, hostaddr=ip4, port=port, user=u.username, password=u.password, dbname=dbname, sslmode='require'))
            # Estrategia 2: Solo IP directa
            estrategias.append(dict(host=ip4, port=port, user=u.username, password=u.password, dbname=dbname, sslmode='require'))
        
        # Estrategia 3: Configuración original URL
        estrategias.append(dict(host=host, port=port, user=u.username, password=u.password, dbname=dbname, sslmode='require'))

        for i, kwargs in enumerate(estrategias):
            try:
                conn = psycopg2.connect(**{**config_base, **kwargs})
                return conn
            except Exception as e:
                print(f"⚠️ Intento DB {i+1} falló: {e}")
                continue
        
        print("❌ ERROR: No se pudo conectar a DATABASE_URL tras todos los intentos.")
        return None

    # 2. Fallback Local (Docker / Desarrollo)
    try:
        return psycopg2.connect(
            host="postgres", 
            database="familychancay",
            user="chancay", 
            password="chancay_123",
            **config_base
        )
    except Exception as e:
        print(f"❌ ERROR DB Local: {e}")
        return None


def serializar(rows):
    """Convierte tipos Postgres (Decimal, Date) a tipos JSON serializables."""
    if not rows:
        return []
    out = []
    for row in rows:
        d = dict(row)
        for k, v in d.items():
            if isinstance(v, Decimal): 
                d[k] = float(v)
            elif isinstance(v, datetime): 
                d[k] = v.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(v, date): 
                d[k] = v.strftime('%Y-%m-%d')
            # Manejo de booleanos para consistencia JSON
            elif isinstance(v, bool):
                d[k] = v 
        out.append(d)
    return out


def tabla_existe(cur, tabla):
    """Verifica si una tabla existe en la BD."""
    try:
        cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)", (tabla,))
        return cur.fetchone()['exists']
    except:
        return False


def columnas_de(cur, tabla):
    """Obtiene lista de columnas de una tabla de forma segura."""
    if not tabla_existe(cur, tabla):
        return []
    try:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (tabla,))
        return [r['column_name'] for r in cur.fetchall()]
    except:
        return []


def init_schema():
    """Asegura que existan columnas críticas agregadas recientemente."""
    conn = get_db()
    if not conn: 
        print("⚠️ No se pudo inicializar schema (DB Down)")
        return
    
    cur = conn.cursor()
    try:
        # Verificar y agregar columnas si faltan
        if tabla_existe(cur, 'productos'):
            cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS imagen TEXT;")
        
        if tabla_existe(cur, 'inventario'):
            cur.execute("ALTER TABLE inventario ADD COLUMN IF NOT EXISTS stock_actual INT DEFAULT 0;")
            
        conn.commit()
        print("✅ Schema verificado/actualizado correctamente")
    except Exception as e:
        print(f"⚠️ Error en init_schema: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def guardar_inventario(cur, sucursal_id, producto_id, variante_id, stock):
    """Inserta inventario probando diferentes esquemas de tabla."""
    queries = [
        # Esquema completo con variante
        ("INSERT INTO inventario (sucursal_id, producto_id, variante_id, stock_actual, stock_minimo, ubicacion_fisica) VALUES (%s,%s,%s,%s,5,%s)",
         (sucursal_id, producto_id, variante_id, stock, f'Estante-A-{producto_id}')),
        # Esquema sin variante
        ("INSERT INTO inventario (sucursal_id, producto_id, stock_actual, stock_minimo, ubicacion_fisica) VALUES (%s,%s,%s,5,%s)",
         (sucursal_id, producto_id, stock, f'Estante-A-{producto_id}')),
        # Esquema alternativo solo variante
        ("INSERT INTO inventario (sucursal_id, variante_id, stock_actual, stock_minimo, ubicacion_fisica) VALUES (%s,%s,%s,5,%s)",
         (sucursal_id, variante_id, stock, f'Estante-A-{producto_id}')),
    ]
    
    for sql, args in queries:
        try:
            cur.execute(sql, args)
            return True
        except pg_errors.ForeignKeyViolation:
            continue  # Probar siguiente esquema
        except Exception:
            continue
    return False


def actualizar_inventario(cur, producto_id, variante_id, stock):
    """Actualiza stock existente o crea registro si no existe."""
    try:
        # Intentar actualizar por producto_id
        cur.execute("UPDATE inventario SET stock_actual=%s WHERE producto_id=%s", (stock, producto_id))
        
        # Si no actualizó nada y hay variante_id, intentar por variante
        if cur.rowcount == 0 and variante_id:
            cur.execute("UPDATE inventario SET stock_actual=%s WHERE variante_id=%s", (stock, variante_id))
            
        # Si sigue sin actualizar, intentar insertar
        if cur.rowcount == 0:
            guardar_inventario(cur, 1, producto_id, variante_id, stock)
    except Exception as e:
        print(f"⚠️ Error actualizando inventario: {e}")


# ==================== ENDPOINTS ====================

@app.route('/api/health', methods=['GET'])
def health():
    conn = get_db()
    ok = conn is not None
    if conn: 
        conn.close()
    return jsonify({"status": "ok" if ok else "db_down", "timestamp": datetime.now().isoformat()})


@app.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    # Credenciales hardcodeadas para demo (usar hash en producción)
    if data.get('user') == 'chancay' and data.get('pass') == 'chancay_123':
        return jsonify({"status": "success", "user": "chancay"})
    return jsonify({"status": "error", "message": "Credenciales inválidas"}), 401


@app.route('/api/catalogos', methods=['GET'])
def get_catalogos():
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
    
    cur = conn.cursor()
    try:
        cats = []
        marcas = []
        
        if tabla_existe(cur, 'categorias'):
            cur.execute("SELECT categoria_id, nombre FROM categorias WHERE estado=True ORDER BY categoria_id")
            cats = serializar(cur.fetchall())
            
        if tabla_existe(cur, 'marcas'):
            cur.execute("SELECT marca_id, nombre FROM marcas WHERE estado=True ORDER BY marca_id")
            marcas = serializar(cur.fetchall())
            
        return jsonify({"categorias": cats, "marcas": marcas})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/productos', methods=['GET'])
def get_productos():
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
        
    categoria = request.args.get('categoria', '')
    busqueda = request.args.get('q', '')
    cur = conn.cursor()
    
    query = """SELECT DISTINCT ON (p.producto_id)
            p.producto_id, p.codigo_producto, p.nombre, p.precio_venta_base,
            c.nombre as categoria, m.nombre as marca, p.estado, p.imagen
        FROM productos p 
        LEFT JOIN categorias c ON p.categoria_id=c.categoria_id
        LEFT JOIN marcas m ON p.marca_id=m.marca_id 
        WHERE p.estado = True"""
        
    params = []
    if categoria and categoria.lower() != 'todos':
        query += " AND LOWER(c.nombre) = LOWER(%s)"
        params.append(categoria)
    if busqueda:
        query += " AND (p.nombre ILIKE %s OR p.codigo_producto ILIKE %s)"
        params.extend([f"%{busqueda}%", f"%{busqueda}%"])
        
    query += " ORDER BY p.producto_id ASC LIMIT 200"
    
    try:
        cur.execute(query, params)
        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        print(f"Error Productos: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/productos/<int:pid>', methods=['GET'])
def get_producto(pid):
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
    
    cur = conn.cursor()
    try:
        cur.execute("""SELECT p.producto_id, p.codigo_producto, p.nombre, p.descripcion,
               p.precio_venta_base, p.categoria_id, p.marca_id, p.imagen,
               c.nombre as categoria, m.nombre as marca
            FROM productos p 
            LEFT JOIN categorias c ON p.categoria_id=c.categoria_id
            LEFT JOIN marcas m ON p.marca_id=m.marca_id 
            WHERE p.producto_id=%s""", (pid,))
            
        p = cur.fetchone()
        if not p: 
            return jsonify({"error": "Producto no encontrado"}), 404
            
        d = serializar([p])[0]
        d['talla'] = ''
        d['color'] = ''
        d['variante_id'] = None
        d['stock'] = 0
        
        # Buscar variante si la tabla existe
        if tabla_existe(cur, 'producto_variantes'):
            cols = columnas_de(cur, 'producto_variantes')
            if 'producto_id' in cols:
                cur.execute("SELECT variante_id, talla, color FROM producto_variantes WHERE producto_id=%s LIMIT 1", (pid,))
                v = cur.fetchone()
                if v:
                    d['talla'] = v.get('talla', '')
                    d['color'] = v.get('color', '')
                    d['variante_id'] = v.get('variante_id')
        
        # Buscar stock
        if tabla_existe(cur, 'inventario'):
            try:
                cur.execute("SELECT stock_actual FROM inventario WHERE producto_id=%s LIMIT 1", (pid,))
                r = cur.fetchone()
                if r and r.get('stock_actual') is not None: 
                    d['stock'] = int(r['stock_actual'])
            except:
                pass
            
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/productos', methods=['POST'])
def crear_producto():
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
        
    d = request.json or {}
    codigo = (d.get('codigo') or '').strip() or f"AUTO-{int(time.time())}{random.randint(10,99)}"
    nombre = (d.get('nombre') or '').strip()
    
    if not nombre: 
        return jsonify({"error": "El nombre es obligatorio"}), 400
        
    cat_id = int(d.get('categoria_id') or 1)
    mar_id = int(d.get('marca_id') or 1)
    precio = float(d.get('precio') or 0)
    talla = (d.get('talla') or '').strip() or 'U'
    color = (d.get('color') or '').strip() or 'N/A'
    stock = int(d.get('stock') or 0)
    imagen = d.get('imagen') or None
    desc = d.get('descripcion') or ''
    
    cur = conn.cursor()
    try:
        cur.execute("""INSERT INTO productos (categoria_id, marca_id, codigo_producto, nombre, descripcion, precio_venta_base, iva, imagen, estado)
            VALUES (%s,%s,%s,%s,%s,%s,18,%s,True) RETURNING producto_id""",
            (cat_id, mar_id, codigo, nombre, desc, precio, imagen))
            
        pid = cur.fetchone()['producto_id']
        sku = f"{codigo}-{talla}-{color}"
        vid = None
        
        if tabla_existe(cur, 'producto_variantes'):
            cols = columnas_de(cur, 'producto_variantes')
            if 'producto_id' in cols:
                cur.execute("""INSERT INTO producto_variantes (producto_id, sku, talla, color, modelo, anio, genero, equipo, temporada, tipo_uniforme, precio, estado)
                    VALUES (%s,%s,%s,%s,%s,'2026','Unisex','N/A','2026','General',%s,True) RETURNING variante_id""",
                    (pid, sku, talla, color, nombre, precio))
                vid = cur.fetchone()['variante_id']
            
        guardar_inventario(cur, 1, pid, vid, stock)
        conn.commit()
        return jsonify({"status": "ok", "producto_id": pid}), 201
        
    except pg_errors.UniqueViolation:
        conn.rollback()
        return jsonify({"error": f"El código '{codigo}' ya existe."}), 400
    except Exception as e:
        conn.rollback()
        print(f"Error crear producto: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/productos/<int:pid>', methods=['PUT'])
def actualizar_producto(pid):
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
        
    d = request.json or {}
    cur = conn.cursor()
    try:
        sets, params = [], []
        if 'nombre' in d: sets.append("nombre=%s"); params.append(d['nombre'])
        if 'precio' in d: sets.append("precio_venta_base=%s"); params.append(float(d['precio']))
        if 'categoria_id' in d: sets.append("categoria_id=%s"); params.append(int(d['categoria_id']))
        if 'marca_id' in d: sets.append("marca_id=%s"); params.append(int(d['marca_id']))
        if 'descripcion' in d: sets.append("descripcion=%s"); params.append(d['descripcion'])
        if 'imagen' in d: sets.append("imagen=%s"); params.append(d['imagen'])
        
        if sets:
            params.append(pid)
            cur.execute(f"UPDATE productos SET {', '.join(sets)} WHERE producto_id=%s", params)
            
        talla = d.get('talla')
        color = d.get('color')
        precio = d.get('precio')
        vid = None
        
        if tabla_existe(cur, 'producto_variantes'):
            cur.execute("SELECT variante_id FROM producto_variantes WHERE producto_id=%s LIMIT 1", (pid,))
            vr = cur.fetchone()
            if vr:
                vsets, vparams = [], []
                if talla is not None: vsets.append("talla=%s"); vparams.append(talla)
                if color is not None: vsets.append("color=%s"); vparams.append(color)
                if precio is not None: vsets.append("precio=%s"); vparams.append(float(precio))
                if vsets:
                    vparams.append(vr['variante_id'])
                    cur.execute(f"UPDATE producto_variantes SET {', '.join(vsets)} WHERE variante_id=%s", vparams)
                vid = vr['variante_id']
                
        if 'stock' in d: 
            actualizar_inventario(cur, pid, vid, int(d['stock']))
            
        conn.commit()
        return jsonify({"status": "ok"})
    except Exception as e:
        conn.rollback()
        print(f"Error update producto: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/productos/<int:pid>', methods=['DELETE'])
def eliminar_producto(pid):
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
    cur = conn.cursor()
    try:
        cur.execute("UPDATE productos SET estado=False WHERE producto_id=%s", (pid,))
        conn.commit()
        return jsonify({"status": "ok"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/ventas', methods=['GET'])
def get_ventas():
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
        
    busqueda = request.args.get('q', '')
    fecha_ini = request.args.get('fecha_inicio', '')
    fecha_fin = request.args.get('fecha_fin', '')
    cur = conn.cursor()
    
    # Verificar tablas necesarias
    tablas_necesarias = ['ventas', 'clientes', 'empleados', 'metodos_pago']
    if not all(tabla_existe(cur, t) for t in tablas_necesarias):
        return jsonify([])
    
    query = """SELECT v.numero_venta, v.fecha_venta, v.total, v.estado_venta,
               cl.nombres || ' ' || cl.apellidos as cliente, 
               e.nombres || ' ' || e.apellidos as vendedor,
               mp.nombre_metodo as metodo_pago
        FROM ventas v 
        JOIN clientes cl ON v.cliente_id = cl.cliente_id
        JOIN empleados e ON v.empleado_id = e.empleado_id 
        JOIN metodos_pago mp ON v.metodo_pago_id = mp.metodo_pago_id
        WHERE v.estado_venta = 'COMPLETADA'"""
        
    params = []
    if busqueda:
        query += " AND (v.numero_venta ILIKE %s OR cl.nombres ILIKE %s)"
        params.extend([f"%{busqueda}%", f"%{busqueda}%"])
    if fecha_ini: 
        query += " AND v.fecha_venta >= %s"
        params.append(fecha_ini)
    if fecha_fin: 
        query += " AND v.fecha_venta <= %s"
        params.append(fecha_fin + ' 23:59:59')
        
    query += " ORDER BY v.fecha_venta DESC LIMIT 100"
    
    try:
        cur.execute(query, params)
        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        print(f"Error Ventas: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/empleados', methods=['GET'])
def get_empleados():
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
    
    cur = conn.cursor()
    try:
        if not tabla_existe(cur, 'empleados'):
            return jsonify([])
            
        has_roles = tabla_existe(cur, 'roles')
        has_sucursales = tabla_existe(cur, 'sucursales')
        
        query = "SELECT e.codigo_empleado, e.nombres, e.apellidos, e.telefono, e.correo"
        joins = ""
        
        if has_roles:
            query += ", r.nombre_rol as rol"
            joins += " JOIN roles r ON e.rol_id=r.rol_id"
        else:
            query += ", NULL as rol"
            
        if has_sucursales:
            query += ", s.nombre as sucursal"
            joins += " JOIN sucursales s ON e.sucursal_id=s.sucursal_id"
        else:
            query += ", NULL as sucursal"
            
        query += f" FROM empleados e {joins} WHERE e.estado=True ORDER BY e.empleado_id"
        
        cur.execute(query)
        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/proveedores', methods=['GET'])
def get_proveedores():
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
    
    cur = conn.cursor()
    try:
        if not tabla_existe(cur, 'proveedores'):
            return jsonify([])
        cur.execute("SELECT ruc_dni, razon_social, contacto_nombre, telefono, correo, direccion FROM proveedores WHERE estado=True")
        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/estadisticas/kpis', methods=['GET'])
def get_kpis():
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
    
    cur = conn.cursor()
    try:
        total_ventas = 0
        ingresos = 0
        clientes = 0
        productos = 0
        
        if tabla_existe(cur, 'ventas'):
            cur.execute("SELECT COUNT(*) as c, COALESCE(SUM(total),0) as s FROM ventas WHERE estado_venta='COMPLETADA'")
            r = cur.fetchone()
            total_ventas = r['c']
            ingresos = float(r['s'])
            
            cur.execute("SELECT COUNT(DISTINCT cliente_id) as c FROM ventas")
            clientes = cur.fetchone()['c']
            
        if tabla_existe(cur, 'productos'):
            cur.execute("SELECT COUNT(*) as c FROM productos WHERE estado=True")
            productos = cur.fetchone()['c']
            
        return jsonify({
            "total_ventas": total_ventas,
            "ingresos_totales": ingresos,
            "clientes_activos": clientes,
            "productos_activos": productos
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/estadisticas/ventas-mes', methods=['GET'])
def get_ventas_mes():
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
    
    cur = conn.cursor()
    try:
        if not tabla_existe(cur, 'ventas'):
            return jsonify([])
            
        cur.execute("""SELECT TO_CHAR(fecha_venta,'YYYY-MM') as mes, COUNT(*) as cantidad_ventas,
               SUM(total) as total_facturado, AVG(total) as ticket_promedio
               FROM ventas WHERE estado_venta='COMPLETADA'
               GROUP BY TO_CHAR(fecha_venta,'YYYY-MM') ORDER BY mes DESC LIMIT 6""")
        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/estadisticas/top-productos', methods=['GET'])
def get_top_productos():
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
        
    cur = conn.cursor()
    try:
        if not tabla_existe(cur, 'detalle_ventas'):
            return jsonify([])
            
        cols = columnas_de(cur, 'detalle_ventas')
        
        if 'producto_id' in cols:
            cur.execute("""SELECT p.nombre as producto, c.nombre as categoria, m.nombre as marca,
                   SUM(dv.cantidad) as unidades_vendidas, SUM(dv.subtotal) as total_generado
                   FROM detalle_ventas dv 
                   JOIN productos p ON dv.producto_id=p.producto_id
                   LEFT JOIN categorias c ON p.categoria_id=c.categoria_id 
                   LEFT JOIN marcas m ON p.marca_id=m.marca_id
                   GROUP BY p.nombre,c.nombre,m.nombre 
                   ORDER BY unidades_vendidas DESC LIMIT 10""")
        elif 'variante_id' in cols:
            cur.execute("""SELECT p.nombre as producto, c.nombre as categoria, m.nombre as marca,
                   SUM(dv.cantidad) as unidades_vendidas, SUM(dv.subtotal) as total_generado
                   FROM detalle_ventas dv 
                   JOIN producto_variantes pv ON dv.variante_id=pv.variante_id
                   JOIN productos p ON pv.producto_id=p.producto_id
                   LEFT JOIN categorias c ON p.categoria_id=c.categoria_id 
                   LEFT JOIN marcas m ON p.marca_id=m.marca_id
                   GROUP BY p.nombre,c.nombre,m.nombre 
                   ORDER BY unidades_vendidas DESC LIMIT 10""")
        else:
            return jsonify([])
            
        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        print(f"Error Top Productos: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# Inicialización al arrancar
with app.app_context():
    init_schema()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)