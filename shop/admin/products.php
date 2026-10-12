<?php
require dirname(__DIR__) . '/includes/init.php';
require dirname(__DIR__) . '/includes/admin_layout.php';
require_admin();
if (is_post()) {
    csrf_verify();
    $id = int_from($_POST['id'] ?? 0);
    if ($id > 0) { sb_delete('products', ['id' => 'eq.' . $id]); flash('success', 'Product deleted.'); }
    redirect('/admin/products.php');
}
$products = sb_select('products', ['select' => 'id,name,base_price,stock,image_path', 'order' => 'id.asc']);
page_header('Products');
admin_nav();
?>
<h1>Products</h1>
<p><a class="btn" href="/admin/product_form.php">Add product</a></p>
<table>
  <tr><th>ID</th><th>Name</th><th>Price</th><th>Stock</th><th>Image</th><th></th></tr>
<?php foreach ($products as $p): ?>
  <tr>
    <td><?= (int)$p['id'] ?></td><td><?= h($p['name']) ?></td><td><?= h(money($p['base_price'])) ?></td>
    <td><?= (int)$p['stock'] ?></td><td><?= h(basename((string)$p['image_path'])) ?></td>
    <td class="actions">
      <a class="btn alt" href="/admin/product_form.php?id=<?= (int)$p['id'] ?>">Edit</a>
      <form method="post" class="inline" onsubmit="return confirm('Delete this product?')">
        <?= csrf_field() ?><input type="hidden" name="id" value="<?= (int)$p['id'] ?>"><button class="btn danger">Delete</button>
      </form>
    </td>
  </tr>
<?php endforeach; ?>
</table>
<?php page_footer();
