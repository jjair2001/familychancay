# -*- coding: utf-8 -*-
"""
============================================================
  API BACKEND – CHANCAY SPORTS  (Flask + PostgreSQL / Supabase)
============================================================
"""
import os, time, random, socket, traceback
from urllib.parse import urlparse
from datetime import datetime, date
from decimal import Decimal
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors as pg_errors

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}, r"/login": {"origins": "*"}})
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

def get_db():
    db_url = os.environ.get('DATABASE_URL')
    base = {'cursor_factory': RealDictCursor, 'connect_timeout': 10}
    if db_url:
        u = urlparse(db_url); host, port, dbname = u.hostname, u.port or 5432, (u.path or '').lstrip('/')
        ip4 = None
        try:
            infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            if infos: ip4 = infos[0][4][0]
        except Exception: pass
        estrategias = []
        if ip4:
            estrategias.append(dict(host=host, hostaddr=ip4, port=port, user=u.username, password=u.password, dbname=dbname, sslmode='require'))
            estrategias.append(dict(host=ip4, port=port, user=u.username, password=u.password, dbname=dbname, sslmode='require'))
        estrategias.append(dict(host=host, port=port, user=u.username, password=u.password, dbname=dbname, sslmode='require'))
        for i, kw in enumerate(estrategias):
            try: return psycopg2.connect(**{**base, **kw})
            except Exception as e: print(f"⚠️ Intento DB {i+1} falló: {e}")
        print("❌ ERROR: no se pudo conectar a DATABASE_URL."); return None
    try: return psycopg2.connect(host="postgres", database="familychancay", user="chancay", password="chancay_123", **base)
    except Exception as e: print(f"❌ ERROR DB Local: {e}"); return None

def serializar(rows):
    if not rows: return []
    out = []
    for row in rows:
        d = dict(row)
        for k, v in d.items():
            if isinstance(v, Decimal): d[k] = float(v)
            elif isinstance(v, datetime): d[k] = v.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(v, date): d[k] = v.strftime('%Y-%m-%d')
        out.append(d)
    return out

def tabla_existe(cur, tabla):
    try:
        cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)", (tabla,))
        return cur.fetchone()['exists']
    except Exception: return False

def columnas_de(cur, tabla):
    if not tabla_existe(cur, tabla): return []
    try:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (tabla,))
        return [r['column_name'] for r in cur.fetchall()]
    except Exception: return []

def guardar_inventario(cur, sucursal_id, producto_id, variante_id, stock):
    queries = [
        ("INSERT INTO inventario (sucursal_id,producto_id,variante_id,stock_actual,stock_minimo,ubicacion_fisica) VALUES (%s,%s,%s,%s,5,%s)", (sucursal_id, producto_id, variante_id, stock, f'Estante-A-{producto_id}')),
        ("INSERT INTO inventario (sucursal_id,producto_id,stock_actual,stock_minimo,ubicacion_fisica) VALUES (%s,%s,%s,5,%s)", (sucursal_id, producto_id, stock, f'Estante-A-{producto_id}')),
        ("INSERT INTO inventario (sucursal_id,variante_id,stock_actual,stock_minimo,ubicacion_fisica) VALUES (%s,%s,%s,5,%s)", (sucursal_id, variante_id, stock, f'Estante-A-{producto_id}')),
    ]
    for sql, args in queries:
        try: cur.execute(sql, args); return True
        except Exception: continue
    return False

def actualizar_inventario(cur, producto_id, variante_id, stock):
    try:
        cur.execute("UPDATE inventario SET stock_actual=%s WHERE producto_id=%s", (stock, producto_id))
        if cur.rowcount == 0 and variante_id: cur.execute("UPDATE inventario SET stock_actual=%s WHERE variante_id=%s", (stock, variante_id))
        if cur.rowcount == 0: guardar_inventario(cur, 1, producto_id, variante_id, stock)
    except Exception as e: print(f"⚠️ Error actualizando inventario: {e}")

def obtener_stock(cur, pid):
    if not tabla_existe(cur, 'inventario'): return 0
    cols = columnas_de(cur, 'inventario')
    try:
        if 'producto_id' in cols and 'stock_actual' in cols:
            cur.execute("SELECT COALESCE(SUM(stock_actual),0) AS stock FROM inventario WHERE producto_id=%s", (pid,))
            r = cur.fetchone(); return int(r['stock']) if r else 0
    except Exception: pass
    return 0

def init_schema():
    conn = get_db()
    if not conn: print("⚠️ No se pudo inicializar schema"); return
    cur = conn.cursor()
    try:
        if tabla_existe(cur, 'productos'): cur.execute("ALTER TABLE productos ADD COLUMN IF NOT EXISTS imagen TEXT;")
        if tabla_existe(cur, 'inventario'): cur.execute("ALTER TABLE inventario ADD COLUMN IF NOT EXISTS stock_actual INT DEFAULT 0;")
        cur.execute("""CREATE TABLE IF NOT EXISTS usuarios (usuario_id SERIAL PRIMARY KEY, nombre VARCHAR(150) NOT NULL, email VARCHAR(150) UNIQUE NOT NULL, password VARCHAR(255) NOT NULL, fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP, estado BIT DEFAULT B'1')""")
        if tabla_existe(cur, 'empleados'):
            for col, tipo in [('horario','VARCHAR(100)'), ('sueldo','DECIMAL(12,2)'), ('tipo_empleado','VARCHAR(50)'), ('fecha_ingreso','DATE')]:
                cur.execute(f"ALTER TABLE empleados ADD COLUMN IF NOT EXISTS {col} {tipo};")
        conn.commit(); print("✅ Schema verificado / actualizado correctamente")
    except Exception as e: print(f"⚠️ Error en init_schema: {e}"); conn.rollback()
    finally: cur.close(); conn.close()

@app.route('/')
def home(): return jsonify({"status":"ok","mensaje":"API Family Chancay funcionando"})

@app.route('/api/health', methods=['GET'])
def health():
    conn = get_db(); ok = conn is not None
    if conn: conn.close()
    return jsonify({"status":"ok" if ok else "db_down","timestamp":datetime.now().isoformat()})

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    if data.get('user')=='chancay' and data.get('pass')=='chancay_123': return jsonify({"status":"success","user":"chancay"})
    return jsonify({"status":"error","message":"Credenciales inválidas"}), 401

@app.route('/api/registro', methods=['POST','OPTIONS'])
def registro_usuario():
    if request.method=='OPTIONS': return '',204
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    d = request.get_json(silent=True) or {}
    nombre=(d.get('nombre') or '').strip(); email=(d.get('email') or '').strip().lower(); passw=(d.get('password') or '').strip()
    if not nombre or not email or not passw: return jsonify({"error":"Nombre, email y contraseña son obligatorios"}),400
    cur = conn.cursor()
    try:
        cur.execute("SELECT usuario_id FROM usuarios WHERE LOWER(email)=LOWER(%s)", (email,))
        if cur.fetchone(): return jsonify({"error":"Ya existe una cuenta con ese correo"}),409
        cur.execute("INSERT INTO usuarios (nombre,email,password) VALUES (%s,%s,%s) RETURNING usuario_id",(nombre,email,passw))
        uid = cur.fetchone()['usuario_id']; conn.commit()
        return jsonify({"status":"ok","usuario_id":uid,"nombre":nombre}),201
    except pg_errors.UniqueViolation: conn.rollback(); return jsonify({"error":"Ya existe una cuenta con ese correo"}),409
    except Exception as e: conn.rollback(); print(f"❌ Error registro: {e}"); traceback.print_exc(); return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/login', methods=['POST','OPTIONS'])
def login_usuario():
    if request.method=='OPTIONS': return '',204
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    d = request.get_json(silent=True) or {}
    email=(d.get('email') or '').strip().lower(); passw=(d.get('password') or '').strip()
    cur = conn.cursor()
    try:
        if not tabla_existe(cur,'usuarios'): return jsonify({"error":"No hay usuarios registrados"}),404
        cur.execute("SELECT usuario_id,nombre,email FROM usuarios WHERE LOWER(email)=LOWER(%s) AND password=%s",(email,passw))
        u = cur.fetchone()
        if not u: return jsonify({"error":"Correo o contraseña incorrectos"}),401
        return jsonify({"status":"ok","usuario_id":u['usuario_id'],"nombre":u['nombre'],"email":u['email']}),200
    except Exception as e: print(f"❌ Error login: {e}"); return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/catalogos', methods=['GET'])
def get_catalogos():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    try:
        cats,marcas,sucursales=[],[],[]
        if tabla_existe(cur,'categorias'): cur.execute("SELECT categoria_id,nombre FROM categorias WHERE estado=B'1' ORDER BY categoria_id"); cats=serializar(cur.fetchall())
        if tabla_existe(cur,'marcas'): cur.execute("SELECT marca_id,nombre FROM marcas WHERE estado=B'1' ORDER BY marca_id"); marcas=serializar(cur.fetchall())
        if tabla_existe(cur,'sucursales'): cur.execute("SELECT sucursal_id,nombre FROM sucursales WHERE estado=B'1' ORDER BY sucursal_id"); sucursales=serializar(cur.fetchall())
        return jsonify({"categorias":cats,"marcas":marcas,"sucursales":sucursales})
    except Exception as e: return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/productos', methods=['GET'])
def get_productos():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    categoria=request.args.get('categoria',''); busqueda=request.args.get('q',''); cur=conn.cursor()
    query="""SELECT DISTINCT ON (p.producto_id) p.producto_id,p.codigo_producto,p.nombre,p.precio_venta_base,c.nombre AS categoria,m.nombre AS marca,p.estado,p.imagen
        FROM productos p LEFT JOIN categorias c ON p.categoria_id=c.categoria_id LEFT JOIN marcas m ON p.marca_id=m.marca_id WHERE p.estado=B'1'"""
    params=[]
    if categoria and categoria.lower()!='todos': query+=" AND LOWER(c.nombre)=LOWER(%s)"; params.append(categoria)
    if busqueda: query+=" AND (p.nombre ILIKE %s OR p.codigo_producto ILIKE %s)"; params.extend([f"%{busqueda}%",f"%{busqueda}%"])
    query+=" ORDER BY p.producto_id ASC LIMIT 200"
    try: cur.execute(query,params); return jsonify(serializar(cur.fetchall()))
    except Exception as e: print(f"Error Productos: {e}"); return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/productos/<int:pid>', methods=['GET'])
def get_producto(pid):
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    try:
        cur.execute("""SELECT p.producto_id,p.codigo_producto,p.nombre,p.descripcion,p.precio_venta_base,p.categoria_id,p.marca_id,p.imagen,c.nombre AS categoria,m.nombre AS marca
            FROM productos p LEFT JOIN categorias c ON p.categoria_id=c.categoria_id LEFT JOIN marcas m ON p.marca_id=m.marca_id WHERE p.producto_id=%s""",(pid,))
        p = cur.fetchone()
        if not p: return jsonify({"error":"Producto no encontrado"}),404
        d = serializar([p])[0]; d['talla']=''; d['color']=''; d['variante_id']=None; d['stock']=obtener_stock(cur,pid)
        if tabla_existe(cur,'producto_variantes'):
            cols=columnas_de(cur,'producto_variantes')
            if 'producto_id' in cols:
                cur.execute("SELECT variante_id,talla,color FROM producto_variantes WHERE producto_id=%s LIMIT 1",(pid,))
                v=cur.fetchone()
                if v: d['talla']=v.get('talla','')or''; d['color']=v.get('color','')or''; d['variante_id']=v.get('variante_id')
        return jsonify(d)
    except Exception as e: return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/productos', methods=['POST'])
def crear_producto():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    d = request.get_json(silent=True) or {}
    nombre=(d.get('nombre') or '').strip()
    if not nombre: return jsonify({"error":"El nombre es obligatorio"}),400
    codigo=(d.get('codigo') or '').strip() or f"AUTO-{int(time.time())}{random.randint(10,99)}"
    cat_id=int(d.get('categoria_id') or 1); mar_id=int(d.get('marca_id') or 1); precio=float(d.get('precio') or 0)
    talla=(d.get('talla') or '').strip() or 'U'; color=(d.get('color') or '').strip() or 'N/A'; stock=int(d.get('stock') or 0)
    imagen=d.get('imagen') or None; desc=d.get('descripcion') or ''
    cur = conn.cursor()
    try:
        cur.execute("""INSERT INTO productos (categoria_id,marca_id,codigo_producto,nombre,descripcion,precio_venta_base,iva,imagen,estado) VALUES (%s,%s,%s,%s,%s,%s,18,%s,B'1') RETURNING producto_id""",(cat_id,mar_id,codigo,nombre,desc,precio,imagen))
        pid = cur.fetchone()['producto_id']; sku=f"{codigo}-{talla}-{color}"; vid=None
        if tabla_existe(cur,'producto_variantes'):
            cols=columnas_de(cur,'producto_variantes')
            if 'producto_id' in cols:
                cur.execute("""INSERT INTO producto_variantes (producto_id,sku,talla,color,modelo,anio,genero,equipo,temporada,tipo_uniforme,precio,estado) VALUES (%s,%s,%s,%s,%s,'2026','Unisex','N/A','2026','General',%s,B'1') RETURNING variante_id""",(pid,sku,talla,color,nombre,precio))
                vid = cur.fetchone()['variante_id']
        guardar_inventario(cur,1,pid,vid,stock); conn.commit()
        return jsonify({"status":"ok","producto_id":pid}),201
    except pg_errors.UniqueViolation: conn.rollback(); return jsonify({"error":f"El código '{codigo}' ya existe."}),400
    except Exception as e: conn.rollback(); print(f"Error crear producto: {e}"); return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/productos/<int:pid>', methods=['PUT'])
def actualizar_producto(pid):
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    d = request.get_json(silent=True) or {}; cur = conn.cursor()
    try:
        sets,params=[],[]
        if 'nombre' in d: sets.append("nombre=%s"); params.append(d['nombre'])
        if 'precio' in d: sets.append("precio_venta_base=%s"); params.append(float(d['precio']))
        if 'categoria_id' in d: sets.append("categoria_id=%s"); params.append(int(d['categoria_id']))
        if 'marca_id' in d: sets.append("marca_id=%s"); params.append(int(d['marca_id']))
        if 'descripcion' in d: sets.append("descripcion=%s"); params.append(d['descripcion'])
        if 'imagen' in d: sets.append("imagen=%s"); params.append(d['imagen'])
        if sets: params.append(pid); cur.execute(f"UPDATE productos SET {', '.join(sets)} WHERE producto_id=%s",params)
        talla,color,precio_v,vid=d.get('talla'),d.get('color'),d.get('precio'),None
        if tabla_existe(cur,'producto_variantes'):
            cur.execute("SELECT variante_id FROM producto_variantes WHERE producto_id=%s LIMIT 1",(pid,)); vr=cur.fetchone()
            if vr:
                vid=vr['variante_id']; vsets,vparams=[],[]
                if talla is not None: vsets.append("talla=%s"); vparams.append(talla)
                if color is not None: vsets.append("color=%s"); vparams.append(color)
                if precio_v is not None: vsets.append("precio=%s"); vparams.append(float(precio_v))
                if vsets: vparams.append(vid); cur.execute(f"UPDATE producto_variantes SET {', '.join(vsets)} WHERE variante_id=%s",vparams)
        if 'stock' in d: actualizar_inventario(cur,pid,vid,int(d['stock']))
        conn.commit(); return jsonify({"status":"ok"})
    except Exception as e: conn.rollback(); print(f"Error update producto: {e}"); return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/productos/<int:pid>', methods=['DELETE'])
def eliminar_producto(pid):
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    try: cur.execute("UPDATE productos SET estado=B'0' WHERE producto_id=%s",(pid,)); conn.commit(); return jsonify({"status":"ok"})
    except Exception as e: conn.rollback(); return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/ventas', methods=['GET'])
def get_ventas():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    busqueda=request.args.get('q',''); fecha_ini=request.args.get('fecha_inicio',''); fecha_fin=request.args.get('fecha_fin',''); cur=conn.cursor()
    if not all(tabla_existe(cur,t) for t in ['ventas','clientes','empleados','metodos_pago']): return jsonify([])
    query="""SELECT v.numero_venta,v.fecha_venta,v.total,v.estado_venta,cl.nombres||' '||cl.apellidos AS cliente,e.nombres||' '||e.apellidos AS vendedor,mp.nombre_metodo AS metodo_pago
        FROM ventas v JOIN clientes cl ON v.cliente_id=cl.cliente_id JOIN empleados e ON v.empleado_id=e.empleado_id JOIN metodos_pago mp ON v.metodo_pago_id=mp.metodo_pago_id WHERE v.estado_venta='COMPLETADA'"""
    params=[]
    if busqueda: query+=" AND (v.numero_venta ILIKE %s OR cl.nombres ILIKE %s OR cl.apellidos ILIKE %s)"; params.extend([f"%{busqueda}%",f"%{busqueda}%",f"%{busqueda}%"])
    if fecha_ini: query+=" AND v.fecha_venta >= %s"; params.append(fecha_ini)
    if fecha_fin: query+=" AND v.fecha_venta <= %s"; params.append(fecha_fin+' 23:59:59')
    query+=" ORDER BY v.fecha_venta DESC LIMIT 100"
    try: cur.execute(query,params); return jsonify(serializar(cur.fetchall()))
    except Exception as e: print(f"Error Ventas: {e}"); return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/pedidos', methods=['POST','OPTIONS'])
def crear_pedido_web():
    if request.method=='OPTIONS': return '',204
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    d = request.get_json(silent=True) or {}; cur = conn.cursor()
    try:
        nombre=(d.get('cliente') or 'Cliente Web').strip(); telefono=(d.get('telefono') or '').strip(); direccion=(d.get('direccion') or '').strip()
        ciudad=(d.get('ciudad') or '').strip(); provincia=(d.get('provincia') or '').strip(); pago=(d.get('metodo_pago') or 'TRANSFERENCIA').upper()
        items=d.get('items') or d.get('productos') or []
        if not items: return jsonify({"error":"Carrito vacío"}),400
        cliente_id=None
        if tabla_existe(cur,'clientes'):
            cols_c=columnas_de(cur,'clientes')
            if telefono and 'telefono' in cols_c:
                try: cur.execute("SELECT cliente_id FROM clientes WHERE telefono=%s LIMIT 1",(telefono,)); r=cur.fetchone()
                except Exception: r=None
                if r: cliente_id=r['cliente_id']
            if not cliente_id:
                campos,vals=[],[]
                if 'nombres' in cols_c: campos.append("nombres"); vals.append(nombre)
                elif 'nombre' in cols_c: campos.append("nombre"); vals.append(nombre)
                if 'apellidos' in cols_c: campos.append("apellidos"); vals.append("Web")
                if 'dni_ruc' in cols_c: campos.append("dni_ruc"); vals.append(telefono or f"WEB{int(time.time())}")
                if 'telefono' in cols_c: campos.append("telefono"); vals.append(telefono)
                if 'correo' in cols_c: campos.append("correo"); vals.append("")
                if 'direccion' in cols_c: campos.append("direccion"); vals.append(f"{direccion}, {ciudad}, {provincia}".strip(", "))
                if 'estado' in cols_c: campos.append("estado"); vals.append('1')
                if campos: ph=', '.join(['%s']*len(vals)); cur.execute(f"INSERT INTO clientes ({','.join(campos)}) VALUES ({ph}) RETURNING cliente_id",vals); cliente_id=cur.fetchone()['cliente_id']
        metodo_id=1
        if tabla_existe(cur,'metodos_pago'):
            try: cur.execute("SELECT metodo_pago_id FROM metodos_pago WHERE UPPER(nombre_metodo) LIKE %s LIMIT 1",(f"%{pago}%",)); r=cur.fetchone()
            except Exception: r=None
            if r: metodo_id=r['metodo_pago_id']
        total=0.0
        for it in items:
            if isinstance(it,dict): total+=float(it.get('precio') or it.get('price') or 0)*int(it.get('cantidad') or 1)
        num=f"WEB-{int(time.time())}"; cols_v=columnas_de(cur,'ventas'); cv,vv=[],[]
        if 'numero_venta' in cols_v: cv.append("numero_venta"); vv.append(num)
        if 'fecha_venta' in cols_v: cv.append("fecha_venta"); vv.append(datetime.now())
        if 'total' in cols_v: cv.append("total"); vv.append(total)
        if 'subtotal' in cols_v: cv.append("subtotal"); vv.append(total)
        if 'descuento' in cols_v: cv.append("descuento"); vv.append(0)
        if 'estado_venta' in cols_v: cv.append("estado_venta"); vv.append('PENDIENTE')
        if 'cliente_id' in cols_v and cliente_id: cv.append("cliente_id"); vv.append(cliente_id)
        if 'sucursal_id' in cols_v: cv.append("sucursal_id"); vv.append(1)
        if 'empleado_id' in cols_v: cv.append("empleado_id"); vv.append(1)
        if 'metodo_pago_id' in cols_v: cv.append("metodo_pago_id"); vv.append(metodo_id)
        ph=', '.join(['%s']*len(vv)); cur.execute(f"INSERT INTO ventas ({','.join(cv)}) VALUES ({ph}) RETURNING venta_id",vv); venta_id=cur.fetchone()['venta_id']
        if tabla_existe(cur,'detalle_ventas'):
            cols_dv=columnas_de(cur,'detalle_ventas')
            for it in items:
                if not isinstance(it,dict): continue
                pu=float(it.get('precio') or 0); cant=int(it.get('cantidad') or 1); pid=it.get('producto_id') or it.get('id'); vid=it.get('variante_id')
                cd,vd=["venta_id"],[venta_id]
                if 'producto_id' in cols_dv and pid: cd.append("producto_id"); vd.append(pid)
                if 'variante_id' in cols_dv and vid: cd.append("variante_id"); vd.append(vid)
                if 'cantidad' in cols_dv: cd.append("cantidad"); vd.append(cant)
                if 'precio_unitario' in cols_dv: cd.append("precio_unitario"); vd.append(pu)
                if 'subtotal' in cols_dv: cd.append("subtotal"); vd.append(pu*cant)
                ph=', '.join(['%s']*len(vd))
                try: cur.execute(f"INSERT INTO detalle_ventas ({','.join(cd)}) VALUES ({ph})",vd)
                except Exception as e: print(f"⚠️ Detalle falló: {e}")
                if pid and tabla_existe(cur,'inventario'):
                    try: cur.execute("UPDATE inventario SET stock_actual=GREATEST(stock_actual-%s,0) WHERE producto_id=%s",(cant,pid))
                    except Exception: pass
        conn.commit(); return jsonify({"status":"ok","venta_id":venta_id,"numero_venta":num,"total":total}),201
    except Exception as e: conn.rollback(); print(f"❌ Error pedido web: {e}"); traceback.print_exc(); return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/facturas', methods=['GET'])
def get_facturas():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    busqueda=request.args.get('q',''); fecha_ini=request.args.get('fecha_inicio',''); fecha_fin=request.args.get('fecha_fin','')
    try:
        if not all(tabla_existe(cur,t) for t in ['ventas','clientes']): return jsonify([])
        query="""SELECT v.venta_id,v.numero_venta,v.fecha_venta,v.subtotal,v.descuento,v.total,v.estado_venta,COALESCE(cl.nombres,'')||' '||COALESCE(cl.apellidos,'') AS cliente,cl.telefono AS cliente_telefono,cl.direccion AS cliente_direccion,mp.nombre_metodo AS metodo_pago
            FROM ventas v LEFT JOIN clientes cl ON v.cliente_id=cl.cliente_id LEFT JOIN metodos_pago mp ON v.metodo_pago_id=mp.metodo_pago_id WHERE 1=1"""
        params=[]
        if busqueda: query+=" AND (v.numero_venta ILIKE %s OR cl.nombres ILIKE %s OR cl.apellidos ILIKE %s)"; params.extend([f"%{busqueda}%",f"%{busqueda}%",f"%{busqueda}%"])
        if fecha_ini: query+=" AND v.fecha_venta >= %s"; params.append(fecha_ini)
        if fecha_fin: query+=" AND v.fecha_venta <= %s"; params.append(fecha_fin+' 23:59:59')
        query+=" ORDER BY v.fecha_venta DESC LIMIT 200"
        cur.execute(query,params); facturas=serializar(cur.fetchall())
        if tabla_existe(cur,'detalle_ventas'):
            for f in facturas:
                cols_dv=columnas_de(cur,'detalle_ventas')
                if 'producto_id' in cols_dv: cur.execute("""SELECT dv.cantidad,dv.precio_unitario,dv.subtotal,COALESCE(p.nombre,'Producto') AS producto,COALESCE(c.nombre,'') AS categoria FROM detalle_ventas dv LEFT JOIN productos p ON dv.producto_id=p.producto_id LEFT JOIN categorias c ON p.categoria_id=c.categoria_id WHERE dv.venta_id=%s""",(f['venta_id'],))
                else: cur.execute("SELECT cantidad,precio_unitario,subtotal FROM detalle_ventas WHERE venta_id=%s",(f['venta_id'],))
                f['detalles']=serializar(cur.fetchall())
        return jsonify(facturas)
    except Exception as e: print(f"Error Facturas: {e}"); traceback.print_exc(); return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/clientes', methods=['GET'])
def get_clientes():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    try:
        if not tabla_existe(cur,'clientes'): return jsonify([])
        cols=columnas_de(cur,'clientes'); campos="cliente_id,nombres,apellidos"
        if 'telefono' in cols: campos+=", telefono"
        if 'correo' in cols: campos+=", correo"
        cur.execute(f"SELECT {campos} FROM clientes WHERE estado=B'1' ORDER BY nombres LIMIT 200"); return jsonify(serializar(cur.fetchall()))
    except Exception as e: return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/empleados', methods=['GET'])
def get_empleados():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    try:
        if not tabla_existe(cur,'empleados'): return jsonify([])
        has_roles=tabla_existe(cur,'roles'); has_sucursales=tabla_existe(cur,'sucursales')
        cols_e=columnas_de(cur,'empleados')
        query="SELECT e.empleado_id,e.codigo_empleado,e.nombres,e.apellidos,e.telefono,e.correo"
        if 'horario' in cols_e: query+=", e.horario"
        if 'sueldo' in cols_e: query+=", e.sueldo"
        if 'tipo_empleado' in cols_e: query+=", e.tipo_empleado"
        if 'fecha_ingreso' in cols_e: query+=", e.fecha_ingreso"
        joins=""
        if has_roles: query+=", r.nombre_rol AS rol"; joins+=" JOIN roles r ON e.rol_id=r.rol_id"
        else: query+=", NULL AS rol"
        if has_sucursales: query+=", s.nombre AS sucursal"; joins+=" JOIN sucursales s ON e.sucursal_id=s.sucursal_id"
        else: query+=", NULL AS sucursal"
        query+=f" FROM empleados e {joins} WHERE e.estado=B'1' ORDER BY e.empleado_id"
        cur.execute(query); return jsonify(serializar(cur.fetchall()))
    except Exception as e: return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/empleados', methods=['POST'])
def crear_empleado():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    d = request.get_json(silent=True) or {}
    nombres=(d.get('nombres') or '').strip(); apellidos=(d.get('apellidos') or '').strip()
    if not nombres: return jsonify({"error":"El nombre es obligatorio"}),400
    cur = conn.cursor()
    try:
        cols=columnas_de(cur,'empleados')
        campos=["nombres","apellidos","estado"]; vals=[nombres,apellidos,'1']
        if 'codigo_empleado' in cols: campos.append("codigo_empleado"); vals.append((d.get('codigo_empleado') or f"EMP-{int(time.time())}"))
        if 'telefono' in cols: campos.append("telefono"); vals.append(d.get('telefono') or '')
        if 'correo' in cols: campos.append("correo"); vals.append(d.get('correo') or '')
        if 'rol_id' in cols: campos.append("rol_id"); vals.append(int(d.get('rol_id') or 2))
        if 'sucursal_id' in cols: campos.append("sucursal_id"); vals.append(int(d.get('sucursal_id') or 1))
        if 'horario' in cols: campos.append("horario"); vals.append(d.get('horario') or '')
        if 'sueldo' in cols: campos.append("sueldo"); vals.append(float(d.get('sueldo') or 0))
        if 'tipo_empleado' in cols: campos.append("tipo_empleado"); vals.append(d.get('tipo_empleado') or 'Empleado')
        if 'fecha_ingreso' in cols: campos.append("fecha_ingreso"); vals.append(d.get('fecha_ingreso') or date.today())
        ph=', '.join(['%s']*len(vals))
        cur.execute(f"INSERT INTO empleados ({','.join(campos)}) VALUES ({ph}) RETURNING empleado_id",vals)
        eid=cur.fetchone()['empleado_id']; conn.commit()
        return jsonify({"status":"ok","empleado_id":eid}),201
    except Exception as e: conn.rollback(); print(f"Error crear empleado: {e}"); return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/proveedores', methods=['GET'])
def get_proveedores():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    try:
        if not tabla_existe(cur,'proveedores'): return jsonify([])
        cols=columnas_de(cur,'proveedores'); campos=[c for c in ['proveedor_id','ruc_dni','razon_social','contacto_nombre','telefono','correo','direccion'] if c in cols]
        if not campos: return jsonify([])
        cur.execute(f"SELECT {', '.join(campos)} FROM proveedores WHERE estado=B'1' ORDER BY 1 LIMIT 200"); return jsonify(serializar(cur.fetchall()))
    except Exception as e: return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/sucursales', methods=['GET'])
def get_sucursales():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    try:
        if not tabla_existe(cur,'sucursales'): return jsonify([])
        cur.execute("SELECT sucursal_id,nombre,direccion,telefono FROM sucursales WHERE estado=B'1' ORDER BY sucursal_id"); return jsonify(serializar(cur.fetchall()))
    except Exception as e: return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/estadisticas/kpis', methods=['GET'])
def get_kpis():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    try:
        total_ventas,ingresos,clientes,productos,hoy_ventas,hoy_ingresos=0,0.0,0,0,0,0.0
        if tabla_existe(cur,'ventas'):
            cur.execute("SELECT COUNT(*) AS c,COALESCE(SUM(total),0) AS s FROM ventas"); r=cur.fetchone(); total_ventas=r['c']; ingresos=float(r['s'])
            cur.execute("SELECT COUNT(DISTINCT cliente_id) AS c FROM ventas"); clientes=cur.fetchone()['c']
            cur.execute("SELECT COUNT(*) AS c,COALESCE(SUM(total),0) AS s FROM ventas WHERE fecha_venta::date=CURRENT_DATE"); r2=cur.fetchone(); hoy_ventas=r2['c']; hoy_ingresos=float(r2['s'])
        if tabla_existe(cur,'productos'): cur.execute("SELECT COUNT(*) AS c FROM productos WHERE estado=B'1'"); productos=cur.fetchone()['c']
        return jsonify({"total_ventas":total_ventas,"ingresos_totales":ingresos,"clientes_activos":clientes,"productos_activos":productos,"hoy_ventas":hoy_ventas,"hoy_ingresos":hoy_ingresos})
    except Exception as e: return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/estadisticas/ventas-mes', methods=['GET'])
def get_ventas_mes():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    try:
        if not tabla_existe(cur,'ventas'): return jsonify([])
        cur.execute("""SELECT TO_CHAR(fecha_venta,'YYYY-MM') AS mes,COUNT(*) AS cantidad_ventas,SUM(total) AS total_facturado,COALESCE(AVG(total),0) AS ticket_promedio FROM ventas GROUP BY TO_CHAR(fecha_venta,'YYYY-MM') ORDER BY mes DESC LIMIT 6""")
        return jsonify(serializar(cur.fetchall()))
    except Exception as e: return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

@app.route('/api/estadisticas/ventas-dia', methods=['GET'])
def get_ventas_dia():
    conn = get_db()
    if not conn: return jsonify({"error":"DB Down"}),503
    cur = conn.cursor()
    try:
        if not tabla_existe(cur,'ventas'): return jsonify([])
        cur.execute("""SELECT TO_CHAR(fecha_venta,'YYYY-MM-DD') AS dia,COUNT(*) AS cantidad_ventas,COALESCE(SUM(total),0) AS total_facturado FROM ventas WHERE fecha_venta >= CURRENT_DATE - INTERVAL '14 days' GROUP BY TO_CHAR(fecha_venta,'YYYY-MM-DD') ORDER BY dia ASC""")
        return jsonify(serializar(cur.fetchall()))
    except Exception as e: return jsonify({"error":str(e)}),500
    finally: cur.close(); conn.close()

with app.app_context(): init_schema()
if __name__=='__main__':
    port=int(os.environ.get('PORT',5000)); debug=os.environ.get('FLASK_DEBUG','0')=='1'
    app.run(host='0.0.0.0',port=port,debug=debug)
