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

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024


def get_db():
    """
    Establece conexión con PostgreSQL.
    Intenta primero conexión local (Docker) y luego vía DATABASE_URL con fallback a IPv4.
    """
    db_url = os.environ.get('DATABASE_URL')
    
    # Conexión local (Docker / Desarrollo)
    if not db_url:
        try:
            return psycopg2.connect(
                host="postgres", 
                database="familychancay",
                user="chancay", 
                password="chancay_123", 
                cursor_factory=RealDictCursor
            )
        except Exception as e:
            print(f"ERROR DB local: {e}")
            return None

    # Conexión remota / Producción
    u = urlparse(db_url)
    host = u.hostname
    ip4 = None
    
    # Intento de resolución IPv4 explícita para evitar problemas de DNS en algunos hosts
    try:
        infos = socket.getaddrinfo(host, 5432, socket.AF_INET, socket.SOCK_STREAM)
        if infos: 
            ip4 = infos[0][4][0]
        print(f"🔎 IPv4 de {host} = {ip4}")
    except Exception as e:
        print(f"⚠️ no resolví IPv4: {e}")

    base = dict(
        user=u.username, 
        password=u.password,
        dbname=(u.path or '').lstrip('/'), 
        port=(u.port or 5432),
        cursor_factory=RealDictCursor
    )
    
    estrategias = []
    if ip4:
        estrategias.append(("IPv4 por hostaddr", dict(host=host, hostaddr=ip4, sslmode='require', **base)))
        estrategias.append(("IPv4 directa",      dict(host=ip4, sslmode='require', **base)))
    estrategias.append(("host original",         dict(host=host, sslmode='require', **base)))

    last_error = None
    for nombre, kw in estrategias:
        try:
            print(f"🔌 intento: {nombre}")
            c = psycopg2.connect(**kw)
            print(f"✅ CONECTÓ con: {nombre}")
            return c
        except Exception as e:
            print(f"❌ falló {nombre}: {e}")
            last_error = e
            
    print(f"ERROR DB: todas fallaron. última: {last_error}")
    return None


def serializar(rows):
    """Convierte tipos de datos complejos de Postgres a tipos nativos de Python/JSON."""
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
        out.append(d)
    return out


def columnas_de(tabla):
    """Obtiene dinámicamente las columnas existentes de una tabla."""
    conn = get_db()
    if not conn: 
        return []
    cur = conn.cursor()
    try:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (tabla,))
        return [r['column_name'] for r in cur.fetchall()]
    except Exception:
        return []
    finally:
        cur.close()
        conn.close()


def init_schema():
    """Asegura que existan columnas críticas agregadas recientemente."""
    conn = get_db()
    if not conn: 
        return
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS imagen TEXT;")
        cur.execute("ALTER TABLE inventario ADD COLUMN IF NOT EXISTS stock_actual INT DEFAULT 0;")
        conn.commit()
        print("✅ Schema OK (imagen / stock_actual)")
    except Exception as e:
        print(f"⚠️ init_schema: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def guardar_inventario(cur, sucursal_id, producto_id, variante_id, stock):
    """Intenta insertar inventario probando diferentes combinaciones de claves foráneas."""
    queries = [
        ("INSERT INTO inventario (sucursal_id,producto_id,variante_id,stock_actual,stock_minimo,ubicacion_fisica) VALUES (%s,%s,%s,%s,5,%s)",
         (sucursal_id, producto_id, variante_id, stock, f'Estante-A-{producto_id}')),
        ("INSERT INTO inventario (sucursal_id,producto_id,stock_actual,stock_minimo,ubicacion_fisica) VALUES (%s,%s,%s,5,%s)",
         (sucursal_id, producto_id, stock, f'Estante-A-{producto_id}')),
        ("INSERT INTO inventario (sucursal_id,variante_id,stock_actual,stock_minimo,ubicacion_fisica) VALUES (%s,%s,%s,5,%s)",
         (sucursal_id, variante_id, stock, f'Estante-A-{producto_id}')),
    ]
    for sql, args in queries:
        try:
            cur.execute(sql, args)
            return
        except Exception:
            pass


def actualizar_inventario(cur, producto_id, variante_id, stock):
    """Actualiza stock existente o crea registro si no existe."""
    try:
        cur.execute("UPDATE inventario SET stock_actual=%s WHERE producto_id=%s", (stock, producto_id))
        if cur.rowcount == 0 and variante_id:
            cur.execute("UPDATE inventario SET stock_actual=%s WHERE variante_id=%s", (stock, variante_id))
        if cur.rowcount == 0:
            guardar_inventario(cur, 1, producto_id, variante_id, stock)
    except Exception as e:
        print(f"⚠️ update inventario: {e}")


# --- ENDPOINTS ---

@app.route('/api/health', methods=['GET'])
def health():
    conn = get_db()
    ok = conn is not None
    if conn: 
        conn.close()
    return jsonify({"status": "ok" if ok else "db_down"})


@app.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    if data.get('user') == 'chancay' and data.get('pass') == 'chancay_123':
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 401


@app.route('/api/catalogos', methods=['GET'])
def get_catalogos():
    conn = get_db()
    if not conn: 
        return jsonify({"error": "DB Down"}), 503
    cur = conn.cursor()
    try:
        cur.execute("SELECT categoria_id, nombre FROM categorias WHERE estado=B'1' ORDER BY categoria_id")
        cats = serializar(cur.fetchall())
        cur.execute("SELECT marca_id, nombre FROM marcas WHERE estado=B'1' ORDER BY marca_id")
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
        JOIN categorias c ON p.categoria_id=c.categoria_id
        JOIN marcas m ON p.marca_id=m.marca_id 
        WHERE p.estado = B'1'"""
        
    params = []
    if categoria and categoria != 'Todos':
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
            JOIN categorias c ON p.categoria_id=c.categoria_id
            JOIN marcas m ON p.marca_id=m.marca_id 
            WHERE p.producto_id=%s""", (pid,))
            
        p = cur.fetchone()
        if not p: 
            return jsonify({"error": "No existe"}), 404
            
        # Buscar variante si la tabla existe
        v = None
        if 'producto_id' in columnas_de('producto_variantes'):
            cur.execute("SELECT variante_id, talla, color FROM producto_variantes WHERE producto_id=%s LIMIT 1", (pid,))
            v = cur.fetchone()
            
        # Buscar stock
        stock = 0
        try:
            cur.execute("SELECT stock_actual FROM inventario WHERE producto_id=%s LIMIT 1", (pid,))
            r = cur.fetchone()
            if r and r['stock_actual'] is not None: 
                stock = int(r['stock_actual'])
        except Exception:
            pass
            
        d = serializar([p])[0]
        d['talla'] = v['talla'] if v else ''
        d['color'] = v['color'] if v else ''
        d['variante_id'] = v['variante_id'] if v else None
        d['stock'] = stock
        
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
            VALUES (%s,%s,%s,%s,%s,%s,18,%s,B'1') RETURNING producto_id""",
            (cat_id, mar_id, codigo, nombre, desc, precio, imagen))
            
        pid = cur.fetchone()['producto_id']
        sku = f"{codigo}-{talla}-{color}"
        vid = None
        
        if 'producto_id' in columnas_de('producto_variantes'):
            cur.execute("""INSERT INTO producto_variantes (producto_id, sku, talla, color, modelo, anio, genero, equipo, temporada, tipo_uniforme, precio, estado)
                VALUES (%s,%s,%s,%s,%s,'2026','Unisex','N/A','2026','General',%s,B'1') RETURNING variante_id""",
                (pid, sku, talla, color, nombre, precio))
            vid = cur.fetchone()['variante_id']
            
        guardar_inventario(cur, 1, pid, vid, stock)
        conn.commit()
        return jsonify({"status": "ok", "producto_id": pid})
        
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({"error": f"El código '{codigo}' ya existe."}), 400
    except Exception as e:
        conn.rollback()
        print(f"Error crear: {e}")
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
        
        if 'producto_id' in columnas_de('producto_variantes'):
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
        print(f"Error update: {e}")
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
        cur.execute("UPDATE productos SET estado=B'0' WHERE producto_id=%s", (pid,))
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
        cur.execute("""SELECT e.codigo_empleado, e.nombres, e.apellidos, r.nombre_rol as rol,
               s.nombre as sucursal, e.telefono, e.correo 
            FROM empleados e
            JOIN roles r ON e.rol_id=r.rol_id 
            JOIN sucursales s ON e.sucursal_id=s.sucursal_id
            WHERE e.estado=B'1' ORDER BY e.empleado_id""")
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
        cur.execute("SELECT ruc_dni, razon_social, contacto_nombre, telefono, correo, direccion FROM proveedores WHERE estado=B'1'")
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
        cur.execute("""SELECT
          (SELECT COUNT(*) FROM ventas WHERE estado_venta='COMPLETADA') as total_ventas,
          (SELECT COALESCE(SUM(total),0) FROM ventas WHERE estado_venta='COMPLETADA') as ingresos_totales,
          (SELECT COUNT(DISTINCT cliente_id) FROM ventas) as clientes_activos,
          (SELECT COUNT(*) FROM productos WHERE estado=B'1') as productos_activos""")
        row = cur.fetchone()
        return jsonify(serializar([row])[0] if row else {})
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
        
    cols = columnas_de('detalle_ventas')
    if not cols: 
        return jsonify([])
        
    cur = conn.cursor()
    try:
        if 'producto_id' in cols:
            cur.execute("""SELECT p.nombre as producto, c.nombre as categoria, m.nombre as marca,
                   SUM(dv.cantidad) as unidades_vendidas, SUM(dv.subtotal) as total_generado
                   FROM detalle_ventas dv 
                   JOIN productos p ON dv.producto_id=p.producto_id
                   JOIN categorias c ON p.categoria_id=c.categoria_id 
                   JOIN marcas m ON p.marca_id=m.marca_id
                   GROUP BY p.nombre,c.nombre,m.nombre 
                   ORDER BY unidades_vendidas DESC LIMIT 10""")
        elif 'variante_id' in cols:
            cur.execute("""SELECT p.nombre as producto, c.nombre as categoria, m.nombre as marca,
                   SUM(dv.cantidad) as unidades_vendidas, SUM(dv.subtotal) as total_generado
                   FROM detalle_ventas dv 
                   JOIN producto_variantes pv ON dv.variante_id=pv.variante_id
                   JOIN productos p ON pv.producto_id=p.producto_id
                   JOIN categorias c ON p.categoria_id=c.categoria_id 
                   JOIN marcas m ON p.marca_id=m.marca_id
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
    app.run(host='0.0.0.0', port=5000)