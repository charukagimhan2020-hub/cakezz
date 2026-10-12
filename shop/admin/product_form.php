<?php
require dirname(__DIR__) . '/includes/init.php';
require dirname(__DIR__) . '/includes/admin_layout.php';
require_admin();
$id = int_from($_GET['id'] ?? ($_POST['id'] ?? 0));
$p = ['name' => '', 'description' => '', 'base_price' => '', 'stock' => '0', 'image_path' => ''];
if ($id > 0) {
    $rows = sb_select('products', ['select' => '*', 'id' => 'eq.' . $id, 'limit' => 1]);
    if (!$rows) { flash('error', 'Product not found.'); redirect('/admin/products.php'); }
    $p = $rows[0];
}
$images = product_images();
$err = '';
if (is_post()) {
    csrf_verify();
    $name = trim((string)($_POST['name'] ?? ''));
    $desc = trim((string)($_POST['description'] ?? ''));
    $priceRaw = $_POST['base_price'] ?? '';
    $stockRaw = $_POST['stock'] ?? '';
    $img = (string)($_POST['image'] ?? '');
    if ($name === '' || strlen($name) > 120) $err = 'Name is required (max 120 characters).';
    elseif (!is_numeric($priceRaw) || (float)$priceRaw < 0) $err = 'Price must be a number, 0 or more.';
    elseif (!is_numeric($stockRaw) || (int)$stockRaw < 0) $err = 'Stock must be 0 or more.';
    elseif ($img !== '' && !in_array($img, $images, true)) $err = 'Pick an image from the list.';
    else {
        $row = ['name' => $name, 'description' => $desc, 'base_price' => (float)$priceRaw, 'stock' => (int)$stockRaw,
                'image_path' => $img !== '' ? 'assets/products/' . $img : null];
        if ($id > 0) sb_update('products', ['id' => 'eq.' . $id], $row);
        else sb_insert('products', $row + ['active' => true]);
        flash('success', 'Product saved.');
        redirect('/admin/products.php');
    }
    $p = ['name' => $name, 'description' => $desc, 'base_price' => $priceRaw, 'stock' => $stockRaw, 'image_path' => $img];
}
$cur = basename((string)($p['image_path'] ?? ''));
page_header($id > 0 ? 'Edit product' : 'Add product');
admin_nav();
?>
<h1><?= $id > 0 ? 'Edit product' : 'Add product' ?></h1>
<?php if ($err): ?><div class="flash error"><?= h($err) ?></div><?php endif; ?>
<form method="post" class="form">
  <?= csrf_field() ?><input type="hidden" name="id" value="<?= (int)$id ?>">
  <label>Name</label><input type="text" name="name" value="<?= h($p['name']) ?>" required>
  <label>Description</label><textarea name="description" rows="4"><?= h($p['description']) ?></textarea>
  <label>Price (Rs)</label><input type="number" name="base_price" step="0.01" min="0" value="<?= h($p['base_price']) ?>" required>
  <label>Stock</label><input type="number" name="stock" min="0" value="<?= h($p['stock']) ?>" required>
  <label>Image (files in shop/assets/products/)</label>
  <select name="image">
    <option value="">(none)</option>
<?php foreach ($images as $f): ?>
    <option value="<?= h($f) ?>" <?= $f === $cur ? 'selected' : '' ?>><?= h($f) ?></option>
<?php endforeach; ?>
  </select>
  <p><button class="btn">Save</button> <a class="btn alt" href="/admin/products.php">Cancel</a></p>
</form>
<?php page_footer();
