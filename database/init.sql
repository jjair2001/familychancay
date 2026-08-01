-- ==========================================
-- FAMILYCHANCAY: ESCALADO MASIVO (CORREGIDO)
-- ==========================================

-- 1. TABLAS MAESTRAS Y ESTRUCTURA (SEGÚN PDF chancay jair.pdf)
CREATE TABLE IF NOT EXISTS roles (rol_id SERIAL PRIMARY KEY, nombre_rol VARCHAR(50), descripcion VARCHAR(200), estado BIT DEFAULT B'1');
CREATE TABLE IF NOT EXISTS sucursales (sucursal_id SERIAL PRIMARY KEY, codigo_sucursal VARCHAR(10), nombre VARCHAR(100), direccion VARCHAR(250), telefono VARCHAR(20), estado BIT DEFAULT B'1');
CREATE TABLE IF NOT EXISTS categorias (categoria_id SERIAL PRIMARY KEY, nombre VARCHAR(100), descripcion TEXT, estado BIT DEFAULT B'1');
CREATE TABLE IF NOT EXISTS marcas (marca_id SERIAL PRIMARY KEY, nombre VARCHAR(100), estado BIT DEFAULT B'1');
CREATE TABLE IF NOT EXISTS metodos_pago (metodo_pago_id SERIAL PRIMARY KEY, nombre_metodo VARCHAR(50), requiere_ref BIT DEFAULT B'0', estado BIT DEFAULT B'1');

CREATE TABLE IF NOT EXISTS proveedores (proveedor_id SERIAL PRIMARY KEY, ruc_dni VARCHAR(20), razon_social VARCHAR(150), contacto_nombre VARCHAR(100), telefono VARCHAR(20), correo VARCHAR(150), direccion VARCHAR(250), estado BIT DEFAULT B'1');
CREATE TABLE IF NOT EXISTS empleados (empleado_id SERIAL PRIMARY KEY, rol_id INT REFERENCES roles(rol_id), sucursal_id INT REFERENCES sucursales(sucursal_id), codigo_empleado VARCHAR(15), nombres VARCHAR(100), apellidos VARCHAR(100), telefono VARCHAR(20), correo VARCHAR(150), fecha_ingreso DATE, estado BIT DEFAULT B'1');
CREATE TABLE IF NOT EXISTS clientes (cliente_id SERIAL PRIMARY KEY, dni_ruc VARCHAR(20), nombres VARCHAR(100), apellidos VARCHAR(100), telefono VARCHAR(20), correo VARCHAR(150), direccion VARCHAR(250), fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP, estado BIT DEFAULT B'1');

CREATE TABLE IF NOT EXISTS productos (producto_id SERIAL PRIMARY KEY, categoria_id INT REFERENCES categorias(categoria_id), marca_id INT REFERENCES marcas(marca_id), codigo_producto VARCHAR(20), nombre VARCHAR(150), descripcion TEXT, precio_venta_base DECIMAL(12,2), iva DECIMAL(5,2), estado BIT DEFAULT B'1');
CREATE TABLE IF NOT EXISTS producto_variantes (variante_id SERIAL PRIMARY KEY, producto_id INT REFERENCES productos(producto_id), sku VARCHAR(40), talla VARCHAR(15), color VARCHAR(50), modelo VARCHAR(100), anio VARCHAR(10), material VARCHAR(50), genero VARCHAR(20), equipo VARCHAR(100), temporada VARCHAR(20), tipo_uniforme VARCHAR(30), codigo_barras VARCHAR(50), precio DECIMAL(12,2), estado BIT DEFAULT B'1');

CREATE TABLE IF NOT EXISTS inventario (inventario_id SERIAL PRIMARY KEY, sucursal_id INT REFERENCES sucursales(sucursal_id), variante_id INT REFERENCES producto_variantes(variante_id), stock_actual INT DEFAULT 0, stock_minimo INT, ubicacion_fisica VARCHAR(50), fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS compras (compra_id SERIAL PRIMARY KEY, proveedor_id INT REFERENCES proveedores(proveedor_id), numero_compra VARCHAR(20), fecha_compra TIMESTAMP DEFAULT CURRENT_TIMESTAMP, subtotal DECIMAL(12,2), impuesto DECIMAL(12,2), total DECIMAL(12,2), estado_compra VARCHAR(15));
CREATE TABLE IF NOT EXISTS detalle_compras (detalle_compra_id SERIAL PRIMARY KEY, compra_id INT REFERENCES compras(compra_id), variante_id INT REFERENCES producto_variantes(variante_id), cantidad INT, costo_unitario DECIMAL(12,2), subtotal DECIMAL(12,2));

CREATE TABLE IF NOT EXISTS ventas (venta_id SERIAL PRIMARY KEY, cliente_id INT REFERENCES clientes(cliente_id), sucursal_id INT REFERENCES sucursales(sucursal_id), empleado_id INT REFERENCES empleados(empleado_id), metodo_pago_id INT REFERENCES metodos_pago(metodo_pago_id), numero_venta VARCHAR(20), fecha_venta TIMESTAMP DEFAULT CURRENT_TIMESTAMP, subtotal DECIMAL(12,2), descuento DECIMAL(12,2), total DECIMAL(12,2), estado_venta VARCHAR(15));
-- CORRECCIÓN CRÍTICA: Se asegura 'INT' antes de REFERENCES para evitar error de sintaxis
CREATE TABLE IF NOT EXISTS detalle_ventas (detalle_venta_id SERIAL PRIMARY KEY, venta_id INT REFERENCES ventas(venta_id), variante_id INT REFERENCES producto_variantes(variante_id), cantidad INT, precio_unitario DECIMAL(12,2), subtotal DECIMAL(12,2));

CREATE TABLE IF NOT EXISTS movimientos_inventario (movimiento_id SERIAL PRIMARY KEY, inventario_id INT REFERENCES inventario(inventario_id), tipo_movimiento VARCHAR(10), cantidad INT, fecha_movimiento TIMESTAMP DEFAULT CURRENT_TIMESTAMP, documento_ref VARCHAR(50), observacion VARCHAR(250));

-- ==========================================
-- 2. CARGA DE DATOS MASIVOS Y REALES
-- ==========================================

INSERT INTO roles (nombre_rol, descripcion) VALUES ('Administrador', 'Acceso Total'), ('Vendedor', 'Gestión de Ventas');
INSERT INTO sucursales (codigo_sucursal, nombre, direccion, telefono) VALUES 
('SUC-001', 'FamilyChancay Central', 'Av. Los Deportes 100, Chancay', '999-000-001'),
('SUC-002', 'FamilyChancay Norte', 'Jr. La Victoria 50, Chancay', '999-000-002');

INSERT INTO categorias (nombre, descripcion) VALUES 
('Ropa Deportiva', 'Camisetas, Pantalones, Chaquetas, Conjuntos'),
('Calzado', 'Zapatos de Fútbol, Running, Basket, Tenis, Senderismo'),
('Accesorios', 'Balones, Guantes, Redes, Cascos, Raquetas, Entrenamiento');

INSERT INTO marcas (nombre) VALUES 
('Nike'), ('Adidas'), ('Puma'), ('Under Armour'), ('Reebok'), ('New Balance'), 
('Asics'), ('Mizuno'), ('Hoka'), ('Brooks'), ('Saucony'), ('Salomon'), 
('Merrell'), ('Columbia'), ('The North Face'), ('Wilson'), ('Head'), 
('Yonex'), ('Babolat'), ('Molten'), ('Mikasa'), ('Spalding'), ('Select'), 
('Uhlsport'), ('Umbro'), ('Lotto'), ('Kappa'), ('Joma'), ('Diadora'), 
('Fila'), ('Decathlon'), ('Speedo'), ('Arena'), ('TYR'), ('Fox Racing'), 
('Shimano'), ('CamelBak'), ('Giro'), ('Rawlings'), ('Easton');

INSERT INTO proveedores (ruc_dni, razon_social, contacto_nombre, telefono, correo, direccion) VALUES 
('20100000001', 'Distribuidora Nike Perú SAC', 'Carlos Mendoza', '987-111-222', 'carlos@nike.pe', 'Av. Javier Prado 1000, Lima'),
('20200000002', 'Adidas Distributors EIRL', 'Ana Torres', '987-333-444', 'ana@adidas.pe', 'Calle Las Begonias 200, Lima'),
('20300000003', 'Importadora Joma Sport', 'Luis Vargas', '987-555-666', 'luis@joma.pe', 'Av. Iquitos 500, Lima'),
('20400000004', 'Balones Select Andina', 'Maria Paz', '987-777-888', 'maria@select.pe', 'Jr. Carabaya 300, Lima');

-- EMPLEADOS ESPECÍFICOS
INSERT INTO empleados (rol_id, sucursal_id, codigo_empleado, nombres, apellidos, telefono, correo, fecha_ingreso) VALUES 
(1, 1, 'EMP-001', 'Chancay', 'Jair', '999-111-001', 'jair.chancay@familychancay.com', '2024-01-15'),
(1, 1, 'EMP-002', 'Chancay', 'Bryan', '999-111-002', 'bryan.chancay@familychancay.com', '2024-02-20');

-- GENERACIÓN DE +100 PRODUCTOS BASE USANDO SERIES
-- Ropa (IDs 1-40)
INSERT INTO productos (categoria_id, marca_id, codigo_producto, nombre, descripcion, precio_venta_base, iva)
SELECT 
    1, -- Ropa Deportiva
    (i % 30) + 1, 
    'ROP-' || LPAD(i::text, 4, '0'),
    CASE WHEN i%3=0 THEN 'Camiseta Técnica Pro '||i WHEN i%3=1 THEN 'Short Entrenamiento Elite '||i ELSE 'Jogger Deportivo Urban '||i END,
    'Prenda de alto rendimiento para deportistas exigentes. Modelo '||i,
    ROUND((RANDOM() * 150 + 50)::numeric, 2), 18.00
FROM generate_series(1, 40) AS i;

-- Calzado (IDs 41-90)
INSERT INTO productos (categoria_id, marca_id, codigo_producto, nombre, descripcion, precio_venta_base, iva)
SELECT 
    2, -- Calzado
    (i % 30) + 1,
    'CAL-' || LPAD((i+40)::text, 4, '0'),
    CASE WHEN i%4=0 THEN 'Zapatilla Running Speed '||(i+40) WHEN i%4=1 THEN 'Botín Fútbol Control '||(i+40) WHEN i%4=2 THEN 'Zapatilla Basket Jump '||(i+40) ELSE 'Bota Senderismo Trail '||(i+40) END,
    'Calzado especializado con tecnología de punta. Modelo '||(i+40),
    ROUND((RANDOM() * 800 + 200)::numeric, 2), 18.00
FROM generate_series(1, 50) AS i;

-- Accesorios (IDs 91-130)
INSERT INTO productos (categoria_id, marca_id, codigo_producto, nombre, descripcion, precio_venta_base, iva)
SELECT 
    3, -- Accesorios
    (i % 30) + 1,
    'ACC-' || LPAD((i+90)::text, 4, '0'),
    CASE WHEN i%3=0 THEN 'Balón Oficial Match '||(i+90) WHEN i%3=1 THEN 'Guante Arquero Pro '||(i+90) ELSE 'Casco Ciclismo Aero '||(i+90) END,
    'Accesorio esencial para entrenamiento y competencia. Modelo '||(i+90),
    ROUND((RANDOM() * 300 + 30)::numeric, 2), 18.00
FROM generate_series(1, 40) AS i;

-- GENERACIÓN DE +2000 VARIANTES (Tallas x Colores x Productos)
INSERT INTO producto_variantes (producto_id, sku, talla, color, modelo, anio, material, genero, equipo, temporada, tipo_uniforme, codigo_barras, precio)
SELECT 
    p.producto_id,
    p.codigo_producto || '-' || t.talla || '-' || c.color,
    t.talla, c.color,
    p.nombre, '2024-2025',
    CASE WHEN p.categoria_id=1 THEN 'Poliéster' WHEN p.categoria_id=2 THEN 'Sintético' ELSE 'PU' END,
    'Unisex', 'N/A', '2024-2025', 'General',
    '750' || LPAD((ROW_NUMBER() OVER())::text, 9, '0'),
    p.precio_venta_base
FROM productos p
CROSS JOIN (VALUES ('35'),('36'),('37'),('38'),('39'),('40'),('41'),('42'),('43'),('44'),('S'),('M'),('L'),('XL')) AS t(talla)
CROSS JOIN (VALUES ('Negro'),('Blanco'),('Azul'),('Rojo')) AS c(color)
WHERE p.estado = B'1';

-- CLIENTES (300)
INSERT INTO clientes (dni_ruc, nombres, apellidos, telefono, correo, direccion)
SELECT '45'||LPAD((20000000+i)::text,8,'0'), (ARRAY['Pedro','Rosa','Luis','Carmen','Jose','Elena','Marco','Diana'])[1+(i%8)], (ARRAY['Diaz','Ruiz','Mendoza','Silva','Ramos','Ortiz','Gutierrez','Paredes'])[1+(i%8)], '999-222-'||LPAD(i::text,3,'0'), 'cli'||i||'.com', 'Jr. Victoria '||i||', Chancay' FROM generate_series(1,300) AS i;

-- INVENTARIO
INSERT INTO inventario (sucursal_id, variante_id, stock_actual, stock_minimo, ubicacion_fisica)
SELECT 1, v.variante_id, (RANDOM()*20)::INT+1, 5, 'Estante '||CHR(65+(v.variante_id%5))||'-'||(v.variante_id%10)
FROM producto_variantes v LIMIT 5000;

INSERT INTO metodos_pago (nombre_metodo, requiere_ref) VALUES ('Efectivo', B'0'), ('Visa/Mastercard', B'1'), ('Yape/Plin', B'1'), ('Transferencia BCP', B'1');

-- GENERACIÓN DE +1000 VENTAS CON FECHAS REALES
INSERT INTO ventas (cliente_id, sucursal_id, empleado_id, metodo_pago_id, numero_venta, fecha_venta, subtotal, descuento, total, estado_venta)
SELECT 
    (i % 300) + 1, 
    (i % 2) + 1, 
    (i % 2) + 1, 
    (i % 4) + 1, 
    'VENT-2026-' || LPAD(i::text, 5, '0'), 
    CURRENT_TIMESTAMP - (RANDOM() * INTERVAL '120 days'), -- Ventas en los últimos 4 meses
    ROUND((RANDOM() * 800 + 50)::numeric, 2),
    ROUND((RANDOM() * 50)::numeric, 2),
    ROUND((RANDOM() * 750 + 50)::numeric, 2),
    'COMPLETADA'
FROM generate_series(1, 1000) AS i;

-- DETALLE DE VENTAS (Vinculando cada venta a una variante existente)
INSERT INTO detalle_ventas (venta_id, variante_id, cantidad, precio_unitario, subtotal)
SELECT 
    v.venta_id,
    (v.venta_id % (SELECT MAX(variante_id) FROM producto_variantes)) + 1,
    (v.venta_id % 3) + 1,
    pv.precio,
    ((v.venta_id % 3) + 1) * pv.precio
FROM ventas v
JOIN producto_variantes pv ON pv.variante_id = ((v.venta_id % (SELECT MAX(variante_id) FROM producto_variantes)) + 1);