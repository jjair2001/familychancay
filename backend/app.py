# -*- coding: utf-8 -*-
"""
============================================================
  API BACKEND – CHANCAY SPORTS
  Flask + PostgreSQL
  Compatible con: Docker, Render, Railway, Local
============================================================
"""

import os
import time
import random
import socket
import traceback
from urllib.parse import urlparse
from datetime import datetime, date
from decimal import Decimal

from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors as pg_errors

# ============================================================
#  CONFIGURACIÓN DE LA APLICACIÓN
# ============================================================
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}, r"/login": {"origins": "*"}})
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB límite


# ============================================================
#  CONEXIÓN A BASE DE DATOS
# ============================================================
def get_db():
    """
    Establece conexión con PostgreSQL.
    1) Intenta DATABASE_URL  (producción)
    2) Fallback local        (Docker / desarrollo)
    """
    db_url = os.environ.get('DATABASE_URL')

    base = {
        'cursor_factory': RealDictCursor,
        'connect_timeout': 10,
    }

    # ---------- 1. Producción ----------
    if db_url:
        u = urlparse(db_url)
        host    = u.hostname
        port    = u.port or 5432
        dbname  = (u.path or '').lstrip('/')

        # Resolución IPv4 explícita (evita timeouts DNS)
        ip4 = None
        try:
            infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            if infos:
                ip4 = infos[0][4][0]
        except Exception:
            pass

        estrategias = []
        if ip4:
            estrategias.append(dict(host=host, hostaddr=ip4, port=port,
                                    user=u.username, password=u.password,
                                    dbname=dbname, sslmode='require'))
            estrategias.append(dict(host=ip4, port=port,
                                    user=u.username, password=u.password,
                                    dbname=dbname, sslmode='require'))
        estrategias.append(dict(host=host, port=port,
                                user=u.username, password=u.password,
                                dbname=dbname, sslmode='require'))

        for i, kw in enumerate(estrategias):
            try:
                return psycopg2.connect(**{**base, **kw})
            except Exception as e:
                print(f"⚠️  Intento DB {i+1} falló: {e}")
        print("❌ ERROR: no se pudo conectar a DATABASE_URL.")
        return None

    # ---------- 2. Local (Docker) ----------
    try:
        return psycopg2.connect(
            host="postgres",
            database="familychancay",
            user="chancay",
            password="chancay_123",
            **base
        )
    except Exception as e:
        print(f"❌ ERROR DB Local: {e}")
        return None


# ============================================================
#  UTILIDADES
# ============================================================
def serializar(rows):
    """Convierte Decimal / datetime / date → tipos JSON."""
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
        out.append(d)
    return out


def tabla_existe(cur, tabla):
    """Verifica si una tabla existe."""
    try:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)",
            (tabla,)
        )
        return cur.fetchone()['exists']
    except Exception:
        return False


def columnas_de(cur, tabla):
    """Lista de columnas de una tabla (lista vacía si no existe)."""
    if not tabla_existe(cur, tabla):
        return []
    try:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s",
            (tabla,)
        )
        return [r['column_name'] for r in cur.fetchall()]
    except Exception:
        return []


def guardar_inventario(cur, sucursal_id, producto_id, variante_id, stock):
    """Inserta inventario probando varios esquemas."""
    queries = [
        ("INSERT INTO inventario (sucursal_id,producto_id,variante_id,stock_actual,stock_minimo,ubicacion_fisica) "
         "VALUES (%s,%s,%s,%s,5,%s)",
         (sucursal_id, producto_id, variante_id, stock, f'Estante-A-{producto_id}')),

        ("INSERT INTO inventario (sucursal_id,producto_id,stock_actual,stock_minimo,ubicacion_fisica) "
         "VALUES (%s,%s,%s,5,%s)",
         (sucursal_id, producto_id, stock, f'Estante-A-{producto_id}')),

        ("INSERT INTO inventario (sucursal_id,variante_id,stock_actual,stock_minimo,ubicacion_fisica) "
         "VALUES (%s,%s,%s,5,%s)",
         (sucursal_id, variante_id, stock, f'Estante-A-{producto_id}')),
    ]
    for sql, args in queries:
        try:
            cur.execute(sql, args)
            return True
        except pg_errors.ForeignKeyViolation:
            continue
        except Exception:
            continue
    return False


def actualizar_inventario(cur, producto_id, variante_id, stock):
    """Actualiza stock existente o crea registro."""
    try:
        cur.execute("UPDATE inventario SET stock_actual=%s WHERE producto_id=%s",
                    (stock, producto_id))
        if cur.rowcount == 0 and variante_id:
            cur.execute("UPDATE inventario SET stock_actual=%s WHERE variante_id=%s",
                        (stock, variante_id))
        if cur.rowcount == 0:
            guardar_inventario(cur, 1, producto_id, variante_id, stock)
    except Exception as e:
        print(f"⚠️  Error actualizando inventario: {e}")


def obtener_stock(cur, pid):
    """Obtiene stock de un producto de forma segura."""
    if not tabla_existe(cur, 'inventario'):
        return 0
    cols = columnas_de(cur, 'inventario')
    try:
        if 'producto_id' in cols and 'stock_actual' in cols:
            cur.execute("SELECT COALESCE(SUM(stock_actual),0) AS stock FROM inventario WHERE producto_id=%s", (pid,))
            r = cur.fetchone()
            return int(r['stock']) if r else 0
    except Exception:
        pass
    return 0


# ============================================================
#  INICIALIZACIÓN DE SCHEMA
# ============================================================
def init_schema():
    """Asegura que existan columnas críticas."""
    conn = get_db()
    if not conn:
        print("⚠️  No se pudo inicializar schema (DB Down)")
        return
    cur = conn.cursor()
    try:
        if tabla_existe(cur, 'productos'):
            cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS imagen TEXT;")
        if tabla_existe(cur, 'inventario'):
            cur.execute("ALTER TABLE inventario ADD COLUMN IF NOT EXISTS stock_actual INT DEFAULT 0;")
        conn.commit()
        print("✅ Schema verificado / actualizado correctamente")
    except Exception as e:
        print(f"⚠️  Error en init_schema: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


# ============================================================
#  ENDPOINTS – SALUD Y LOGIN
# ============================================================
@app.route('/api/health', methods=['GET'])
def health():
    conn = get_db()
    ok = conn is not None
    if conn:
        conn.close()
    return jsonify({
        "status": "ok" if ok else "db_down",
        "timestamp": datetime.now().isoformat()
    })


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    if data.get('user') == 'chancay' and data.get('pass') == 'chancay_123':
        return jsonify({"status": "success", "user": "chancay"})
    return jsonify({"status": "error", "message": "Credenciales inválidas"}), 401


# ============================================================
#  CATÁLOGOS
# ============================================================
@app.route('/api/catalogos', methods=['GET'])
def get_catalogos():
    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503
    cur = conn.cursor()
    try:
        cats, marcas, sucursales = [], [], []

        if tabla_existe(cur, 'categorias'):
            cur.execute("SELECT categoria_id, nombre FROM categorias WHERE estado=TRUE ORDER BY categoria_id")
            cats = serializar(cur.fetchall())

        if tabla_existe(cur, 'marcas'):
            cur.execute("SELECT marca_id, nombre FROM marcas WHERE estado=TRUE ORDER BY marca_id")
            marcas = serializar(cur.fetchall())

        if tabla_existe(cur, 'sucursales'):
            cur.execute("SELECT sucursal_id, nombre FROM sucursales WHERE estado=TRUE ORDER BY sucursal_id")
            sucursales = serializar(cur.fetchall())

        return jsonify({"categorias": cats, "marcas": marcas, "sucursales": sucursales})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================================
#  PRODUCTOS  (CRUD)
# ============================================================
@app.route('/api/productos', methods=['GET'])
def get_productos():
    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503

    categoria = request.args.get('categoria', '')
    busqueda  = request.args.get('q', '')
    cur = conn.cursor()

    query = """
        SELECT DISTINCT ON (p.producto_id)
               p.producto_id, p.codigo_producto, p.nombre,
               p.precio_venta_base, c.nombre AS categoria,
               m.nombre AS marca, p.estado, p.imagen
        FROM productos p
        LEFT JOIN categorias c ON p.categoria_id = c.categoria_id
        LEFT JOIN marcas m     ON p.marca_id     = m.marca_id
        WHERE p.estado = TRUE
    """
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
        cur.execute("""
            SELECT p.producto_id, p.codigo_producto, p.nombre, p.descripcion,
                   p.precio_venta_base, p.categoria_id, p.marca_id, p.imagen,
                   c.nombre AS categoria, m.nombre AS marca
            FROM productos p
            LEFT JOIN categorias c ON p.categoria_id = c.categoria_id
            LEFT JOIN marcas m     ON p.marca_id     = m.marca_id
            WHERE p.producto_id = %s
        """, (pid,))

        p = cur.fetchone()
        if not p:
            return jsonify({"error": "Producto no encontrado"}), 404

        d = serializar([p])[0]
        d['talla']       = ''
        d['color']       = ''
        d['variante_id'] = None
        d['stock']       = obtener_stock(cur, pid)

        # Variante (si existe tabla)
        if tabla_existe(cur, 'producto_variantes'):
            cols = columnas_de(cur, 'producto_variantes')
            if 'producto_id' in cols:
                cur.execute("SELECT variante_id, talla, color FROM producto_variantes WHERE producto_id=%s LIMIT 1", (pid,))
                v = cur.fetchone()
                if v:
                    d['talla']       = v.get('talla', '') or ''
                    d['color']       = v.get('color', '') or ''
                    d['variante_id'] = v.get('variante_id')

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

    d = request.get_json(silent=True) or {}
    nombre = (d.get('nombre') or '').strip()
    if not nombre:
        return jsonify({"error": "El nombre es obligatorio"}), 400

    codigo  = (d.get('codigo') or '').strip() or f"AUTO-{int(time.time())}{random.randint(10, 99)}"
    cat_id  = int(d.get('categoria_id') or 1)
    mar_id  = int(d.get('marca_id') or 1)
    precio  = float(d.get('precio') or 0)
    talla   = (d.get('talla') or '').strip() or 'U'
    color   = (d.get('color') or '').strip() or 'N/A'
    stock   = int(d.get('stock') or 0)
    imagen  = d.get('imagen') or None
    desc    = d.get('descripcion') or ''

    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO productos (categoria_id, marca_id, codigo_producto, nombre,
                                   descripcion, precio_venta_base, iva, imagen, estado)
            VALUES (%s,%s,%s,%s,%s,%s,18,%s,TRUE)
            RETURNING producto_id
        """, (cat_id, mar_id, codigo, nombre, desc, precio, imagen))
        pid = cur.fetchone()['producto_id']

        sku = f"{codigo}-{talla}-{color}"
        vid = None

        if tabla_existe(cur, 'producto_variantes'):
            cols = columnas_de(cur, 'producto_variantes')
            if 'producto_id' in cols:
                cur.execute("""
                    INSERT INTO producto_variantes
                        (producto_id, sku, talla, color, modelo,
                         anio, genero, equipo, temporada, tipo_uniforme, precio, estado)
                    VALUES (%s,%s,%s,%s,%s,'2026','Unisex','N/A','2026','General',%s,TRUE)
                    RETURNING variante_id
                """, (pid, sku, talla, color, nombre, precio))
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

    d   = request.get_json(silent=True) or {}
    cur = conn.cursor()
    try:
        sets, params = [], []
        if 'nombre'       in d: sets.append("nombre=%s");             params.append(d['nombre'])
        if 'precio'       in d: sets.append("precio_venta_base=%s");  params.append(float(d['precio']))
        if 'categoria_id' in d: sets.append("categoria_id=%s");       params.append(int(d['categoria_id']))
        if 'marca_id'     in d: sets.append("marca_id=%s");           params.append(int(d['marca_id']))
        if 'descripcion'  in d: sets.append("descripcion=%s");        params.append(d['descripcion'])
        if 'imagen'       in d: sets.append("imagen=%s");             params.append(d['imagen'])

        if sets:
            params.append(pid)
            cur.execute(f"UPDATE productos SET {', '.join(sets)} WHERE producto_id=%s", params)

        # Variante
        talla, color, precio_v, vid = d.get('talla'), d.get('color'), d.get('precio'), None
        if tabla_existe(cur, 'producto_variantes'):
            cur.execute("SELECT variante_id FROM producto_variantes WHERE producto_id=%s LIMIT 1", (pid,))
            vr = cur.fetchone()
            if vr:
                vid = vr['variante_id']
                vsets, vparams = [], []
                if talla    is not None: vsets.append("talla=%s");  vparams.append(talla)
                if color    is not None: vsets.append("color=%s");  vparams.append(color)
                if precio_v is not None: vsets.append("precio=%s"); vparams.append(float(precio_v))
                if vsets:
                    vparams.append(vid)
                    cur.execute(f"UPDATE producto_variantes SET {', '.join(vsets)} WHERE variante_id=%s", vparams)

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
        cur.execute("UPDATE productos SET estado=FALSE WHERE producto_id=%s", (pid,))
        conn.commit()
        return jsonify({"status": "ok"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================================
#  VENTAS
# ============================================================
@app.route('/api/ventas', methods=['GET'])
def get_ventas():
    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503

    busqueda  = request.args.get('q', '')
    fecha_ini = request.args.get('fecha_inicio', '')
    fecha_fin = request.args.get('fecha_fin', '')
    cur = conn.cursor()

    tablas = ['ventas', 'clientes', 'empleados', 'metodos_pago']
    if not all(tabla_existe(cur, t) for t in tablas):
        return jsonify([])

    query = """
        SELECT v.numero_venta, v.fecha_venta, v.total, v.estado_venta,
               cl.nombres || ' ' || cl.apellidos AS cliente,
               e.nombres  || ' ' || e.apellidos  AS vendedor,
               mp.nombre_metodo                   AS metodo_pago
        FROM ventas v
        JOIN clientes cl      ON v.cliente_id      = cl.cliente_id
        JOIN empleados e      ON v.empleado_id     = e.empleado_id
        JOIN metodos_pago mp  ON v.metodo_pago_id  = mp.metodo_pago_id
        WHERE v.estado_venta = 'COMPLETADA'
    """
    params = []

    if busqueda:
        query += " AND (v.numero_venta ILIKE %s OR cl.nombres ILIKE %s OR cl.apellidos ILIKE %s)"
        params.extend([f"%{busqueda}%", f"%{busqueda}%", f"%{busqueda}%"])
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


@app.route('/api/ventas', methods=['POST'])
def crear_venta():
    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503

    d = request.get_json(silent=True) or {}
    cur = conn.cursor()

    try:
        cliente_id     = int(d.get('cliente_id') or 1)
        empleado_id    = int(d.get('empleado_id') or 1)
        metodo_pago_id = int(d.get('metodo_pago_id') or 1)
        sucursal_id    = int(d.get('sucursal_id') or 1)
        detalles       = d.get('detalles') or []

        if not detalles:
            return jsonify({"error": "Se requiere al menos un detalle de producto"}), 400

        numero_venta = f"V-{int(time.time())}{random.randint(100, 999)}"
        total = 0.0

        # Calcular total
        for det in detalles:
            precio_det = float(det.get('precio') or 0)
            cantidad   = int(det.get('cantidad') or 1)
            total += precio_det * cantidad

        # Insertar venta
        cols_ventas = columnas_de(cur, 'ventas')
        sql_v = """INSERT INTO ventas (numero_venta, cliente_id, empleado_id,
                   metodo_pago_id, sucursal_id, total, estado_venta, fecha_venta)
                   VALUES (%s,%s,%s,%s,%s,%s,'COMPLETADA', NOW())
                   RETURNING venta_id"""
        cur.execute(sql_v, (numero_venta, cliente_id, empleado_id,
                            metodo_pago_id, sucursal_id, total))
        venta_id = cur.fetchone()['venta_id']

        # Insertar detalles y descontar stock
        cols_dv = columnas_de(cur, 'detalle_ventas')
        for det in detalles:
            producto_id = int(det.get('producto_id') or 0)
            variante_id = det.get('variante_id') or None
            cantidad    = int(det.get('cantidad') or 1)
            precio_u    = float(det.get('precio') or 0)
            subtotal    = precio_u * cantidad

            if 'venta_id' in cols_dv and 'producto_id' in cols_dv:
                sql_d = """INSERT INTO detalle_ventas
                           (venta_id, producto_id, variante_id, cantidad, precio_unitario, subtotal)
                           VALUES (%s,%s,%s,%s,%s,%s)"""
                try:
                    cur.execute(sql_d, (venta_id, producto_id, variante_id, cantidad, precio_u, subtotal))
                except Exception:
                    # Fallback sin variante_id
                    sql_d2 = """INSERT INTO detalle_ventas
                                (venta_id, producto_id, cantidad, precio_unitario, subtotal)
                                VALUES (%s,%s,%s,%s,%s)"""
                    cur.execute(sql_d2, (venta_id, producto_id, cantidad, precio_u, subtotal))

            # Descontar stock
            try:
                cur.execute("""UPDATE inventario
                               SET stock_actual = GREATEST(stock_actual - %s, 0)
                               WHERE producto_id = %s""", (cantidad, producto_id))
                if cur.rowcount == 0 and variante_id:
                    cur.execute("""UPDATE inventario
                                   SET stock_actual = GREATEST(stock_actual - %s, 0)
                                   WHERE variante_id = %s""", (cantidad, variante_id))
            except Exception:
                pass

        conn.commit()
        return jsonify({"status": "ok", "venta_id": venta_id, "numero_venta": numero_venta, "total": total}), 201

    except Exception as e:
        conn.rollback()
        print(f"Error crear venta: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================================
#  PEDIDOS WEB  (endpoint que usa el frontend Netlify)
#  Versión tolerante: solo usa las columnas que realmente existen
# ============================================================
@app.route('/api/pedidos', methods=['POST', 'OPTIONS'])
def crear_pedido_web():
    if request.method == 'OPTIONS':
        return '', 204

    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503

    d   = request.get_json(silent=True) or {}
    cur = conn.cursor()

    try:
        nombre    = (d.get('cliente')  or 'Cliente Web').strip()
        telefono  = (d.get('telefono') or '').strip()
        direccion = (d.get('direccion') or '').strip()
        ciudad    = (d.get('ciudad')    or '').strip()
        provincia = (d.get('provincia') or '').strip()
        pago      = (d.get('metodo_pago') or 'TRANSFERENCIA').upper()
        items     = d.get('items') or d.get('productos') or []

        if not items:
            return jsonify({"error": "Carrito vacío"}), 400

        # ---- 1. Cliente (tolerante a columnas) ----
        cliente_id = None
        if tabla_existe(cur, 'clientes'):
            cols_c = columnas_de(cur, 'clientes')

            # Buscar por teléfono si existe la columna
            if telefono and 'telefono' in cols_c:
                try:
                    cur.execute("SELECT cliente_id FROM clientes WHERE telefono=%s LIMIT 1", (telefono,))
                    r = cur.fetchone()
                    if r: cliente_id = r['cliente_id']
                except Exception:
                    pass

            if not cliente_id:
                campos, vals = [], []
                if 'nombres' in cols_c:    campos.append("nombres");    vals.append(nombre)
                elif 'nombre' in cols_c:   campos.append("nombre");     vals.append(nombre)
                if 'apellidos' in cols_c:  campos.append("apellidos");  vals.append("Web")
                if 'apellido' in cols_c:   campos.append("apellido");   vals.append("Web")
                if 'dni_ruc' in cols_c:    campos.append("dni_ruc");    vals.append(telefono or f"WEB{int(time.time())}")
                if 'cedula_ruc' in cols_c: campos.append("cedula_ruc"); vals.append(telefono or f"WEB{int(time.time())}")
                if 'telefono' in cols_c:   campos.append("telefono");   vals.append(telefono)
                if 'correo' in cols_c:     campos.append("correo");     vals.append("")
                if 'email' in cols_c:      campos.append("email");      vals.append("")
                if 'direccion' in cols_c:  campos.append("direccion");  vals.append(f"{direccion}, {ciudad}, {provincia}".strip(", "))
                if 'estado' in cols_c:     campos.append("estado");    vals.append('1')

                if campos:
                    ph = ', '.join(['%s']*len(vals))
                    cur.execute(f"INSERT INTO clientes ({','.join(campos)}) VALUES ({ph}) RETURNING cliente_id", vals)
                    cliente_id = cur.fetchone()['cliente_id']

        # ---- 2. Método de pago ----
        metodo_id = 1
        if tabla_existe(cur, 'metodos_pago'):
            try:
                cur.execute("SELECT metodo_pago_id FROM metodos_pago WHERE UPPER(nombre_metodo) LIKE %s LIMIT 1", (f"%{pago}%",))
                r = cur.fetchone()
                if r: metodo_id = r['metodo_pago_id']
            except Exception:
                pass

        # ---- 3. Total (tolerante) ----
        def _precio(it):
            if isinstance(it, dict):
                return float(it.get('precio') or it.get('price') or it.get('precio_unitario') or 0)
            return 0.0

        def _cantidad(it):
            if isinstance(it, dict):
                return int(it.get('cantidad') or it.get('quantity') or it.get('cant') or 1)
            return 1

        total = sum(_precio(it) * _cantidad(it) for it in items)

        # ---- 4. Venta (tolerante) ----
        num = f"WEB-{int(time.time())}"
        cols_v = columnas_de(cur, 'ventas')
        cv, vv = [], []
        if 'numero_venta'   in cols_v: cv.append("numero_venta");   vv.append(num)
        if 'fecha_venta'    in cols_v: cv.append("fecha_venta");    vv.append(datetime.now())
        if 'total'          in cols_v: cv.append("total");          vv.append(total)
        if 'subtotal'       in cols_v: cv.append("subtotal");       vv.append(total)
        if 'descuento'      in cols_v: cv.append("descuento");      vv.append(0)
        if 'estado_venta'   in cols_v: cv.append("estado_venta");   vv.append('PENDIENTE')
        if 'cliente_id'     in cols_v and cliente_id: cv.append("cliente_id");     vv.append(cliente_id)
        if 'sucursal_id'    in cols_v: cv.append("sucursal_id");    vv.append(1)
        if 'empleado_id'    in cols_v: cv.append("empleado_id");    vv.append(1)
        if 'metodo_pago_id' in cols_v: cv.append("metodo_pago_id"); vv.append(metodo_id)

        ph = ', '.join(['%s']*len(vv))
        cur.execute(f"INSERT INTO ventas ({','.join(cv)}) VALUES ({ph}) RETURNING venta_id", vv)
        venta_id = cur.fetchone()['venta_id']

             # ---- 5. Detalles + stock ----
        if tabla_existe(cur, 'detalle_ventas'):
            cols_dv = columnas_de(cur, 'detalle_ventas')
            for it in items:
                pu   = _precio(it)
                cant = _cantidad(it)
                pid  = (it.get('producto_id') or it.get('id')) if isinstance(it, dict) else None
                vid  = (it.get('variante_id')) if isinstance(it, dict) else None
                cd, vd = ["venta_id"], [venta_id]
                if 'producto_id' in cols_dv and pid: cd.append("producto_id"); vd.append(pid)
                if 'variante_id' in cols_dv and vid: cd.append("variante_id"); vd.append(vid)
                if 'cantidad' in cols_dv:        cd.append("cantidad");        vd.append(cant)
                if 'precio_unitario' in cols_dv: cd.append("precio_unitario"); vd.append(pu)
                if 'subtotal' in cols_dv:        cd.append("subtotal");        vd.append(pu*cant)
                ph = ', '.join(['%s']*len(vd))
                try:
                    cur.execute(f"INSERT INTO detalle_ventas ({','.join(cd)}) VALUES ({ph})", vd)
                except Exception as e:
                    print(f"⚠️ Detalle falló: {e}")
                if pid and tabla_existe(cur, 'inventario'):
                    try:
                        cur.execute("UPDATE inventario SET stock_actual=GREATEST(stock_actual-%s,0) WHERE producto_id=%s", (cant, pid))
                    except Exception:
                        pass


# ============================================================
#  CLIENTES
# ============================================================
@app.route('/api/clientes', methods=['GET'])
def get_clientes():
    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503
    cur = conn.cursor()
    try:
        if not tabla_existe(cur, 'clientes'):
            return jsonify([])
        cols = columnas_de(cur, 'clientes')
        campos = "cliente_id, nombres, apellidos"
        if 'telefono' in cols:
            campos += ", telefono"
        if 'correo' in cols:
            campos += ", correo"
        if 'cedula_ruc' in cols:
            campos += ", cedula_ruc"
        cur.execute(f"SELECT {campos} FROM clientes WHERE estado=TRUE ORDER BY nombres LIMIT 200")
        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/clientes', methods=['POST'])
def crear_cliente():
    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503
    d = request.get_json(silent=True) or {}
    nombres = (d.get('nombres') or '').strip()
    if not nombres:
        return jsonify({"error": "El nombre es obligatorio"}), 400
    cur = conn.cursor()
    try:
        cols = columnas_de(cur, 'clientes')
        campos  = "nombres, apellidos, estado"
        valores = [nombres, (d.get('apellidos') or ''), True]

        if 'cedula_ruc' in cols:
            campos += ", cedula_ruc";   valores.append(d.get('cedula_ruc') or '')
        if 'telefono' in cols:
            campos += ", telefono";      valores.append(d.get('telefono') or '')
        if 'correo' in cols:
            campos += ", correo";        valores.append(d.get('correo') or '')
        if 'direccion' in cols:
            campos += ", direccion";     valores.append(d.get('direccion') or '')

        placeholders = ', '.join(['%s'] * len(valores))
        cur.execute(f"INSERT INTO clientes ({campos}) VALUES ({placeholders}) RETURNING cliente_id", valores)
        cid = cur.fetchone()['cliente_id']
        conn.commit()
        return jsonify({"status": "ok", "cliente_id": cid}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================================
#  EMPLEADOS
# ============================================================
@app.route('/api/empleados', methods=['GET'])
def get_empleados():
    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503
    cur = conn.cursor()
    try:
        if not tabla_existe(cur, 'empleados'):
            return jsonify([])

        has_roles     = tabla_existe(cur, 'roles')
        has_sucursales = tabla_existe(cur, 'sucursales')

        query = "SELECT e.empleado_id, e.codigo_empleado, e.nombres, e.apellidos, e.telefono, e.correo"
        joins = ""

        if has_roles:
            query += ", r.nombre_rol AS rol"
            joins += " JOIN roles r ON e.rol_id = r.rol_id"
        else:
            query += ", NULL AS rol"

        if has_sucursales:
            query += ", s.nombre AS sucursal"
            joins += " JOIN sucursales s ON e.sucursal_id = s.sucursal_id"
        else:
            query += ", NULL AS sucursal"

        query += f" FROM empleados e {joins} WHERE e.estado=TRUE ORDER BY e.empleado_id"

        cur.execute(query)
        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================================
#  PROVEEDORES
# ============================================================
@app.route('/api/proveedores', methods=['GET'])
def get_proveedores():
    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503
    cur = conn.cursor()
    try:
        if not tabla_existe(cur, 'proveedores'):
            return jsonify([])
        cols = columnas_de(cur, 'proveedores')
        campos = []
        for c in ['proveedor_id', 'ruc_dni', 'razon_social', 'contacto_nombre', 'telefono', 'correo', 'direccion']:
            if c in cols:
                campos.append(c)
        if not campos:
            return jsonify([])
        cur.execute(f"SELECT {', '.join(campos)} FROM proveedores WHERE estado=TRUE ORDER BY 1 LIMIT 200")
        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================================
#  SUCURSALES
# ============================================================
@app.route('/api/sucursales', methods=['GET'])
def get_sucursales():
    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503
    cur = conn.cursor()
    try:
        if not tabla_existe(cur, 'sucursales'):
            return jsonify([])
        cur.execute("SELECT sucursal_id, nombre, direccion, telefono FROM sucursales WHERE estado=TRUE ORDER BY sucursal_id")
        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================================
#  ESTADÍSTICAS
# ============================================================
@app.route('/api/estadisticas/kpis', methods=['GET'])
def get_kpis():
    conn = get_db()
    if not conn:
        return jsonify({"error": "DB Down"}), 503
    cur = conn.cursor()
    try:
        total_ventas, ingresos, clientes, productos = 0, 0.0, 0, 0

        if tabla_existe(cur, 'ventas'):
            cur.execute("SELECT COUNT(*) AS c, COALESCE(SUM(total),0) AS s FROM ventas WHERE estado_venta='COMPLETADA'")
            r = cur.fetchone()
            total_ventas = r['c']
            ingresos     = float(r['s'])

            cur.execute("SELECT COUNT(DISTINCT cliente_id) AS c FROM ventas")
            clientes = cur.fetchone()['c']

        if tabla_existe(cur, 'productos'):
            cur.execute("SELECT COUNT(*) AS c FROM productos WHERE estado=TRUE")
            productos = cur.fetchone()['c']

        return jsonify({
            "total_ventas":     total_ventas,
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
        cur.execute("""
            SELECT TO_CHAR(fecha_venta,'YYYY-MM') AS mes,
                   COUNT(*)                          AS cantidad_ventas,
                   SUM(total)                        AS total_facturado,
                   COALESCE(AVG(total),0)            AS ticket_promedio
            FROM ventas
            WHERE estado_venta = 'COMPLETADA'
            GROUP BY TO_CHAR(fecha_venta,'YYYY-MM')
            ORDER BY mes DESC
            LIMIT 6
        """)
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
            cur.execute("""
                SELECT p.nombre AS producto, c.nombre AS categoria, m.nombre AS marca,
                       SUM(dv.cantidad) AS unidades_vendidas,
                       SUM(dv.subtotal) AS total_generado
                FROM detalle_ventas dv
                JOIN productos p      ON dv.producto_id  = p.producto_id
                LEFT JOIN categorias c ON p.categoria_id = c.categoria_id
                LEFT JOIN marcas m     ON p.marca_id     = m.marca_id
                GROUP BY p.nombre, c.nombre, m.nombre
                ORDER BY unidades_vendidas DESC
                LIMIT 10
            """)
        elif 'variante_id' in cols:
            cur.execute("""
                SELECT p.nombre AS producto, c.nombre AS categoria, m.nombre AS marca,
                       SUM(dv.cantidad) AS unidades_vendidas,
                       SUM(dv.subtotal) AS total_generado
                FROM detalle_ventas dv
                JOIN producto_variantes pv ON dv.variante_id  = pv.variante_id
                JOIN productos p           ON pv.producto_id  = p.producto_id
                LEFT JOIN categorias c     ON p.categoria_id  = c.categoria_id
                LEFT JOIN marcas m         ON p.marca_id      = m.marca_id
                GROUP BY p.nombre, c.nombre, m.nombre
                ORDER BY unidades_vendidas DESC
                LIMIT 10
            """)
        else:
            return jsonify([])

        return jsonify(serializar(cur.fetchall()))
    except Exception as e:
        print(f"Error Top Productos: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================================
#  ARRANQUE
# ============================================================
with app.app_context():
    init_schema()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
