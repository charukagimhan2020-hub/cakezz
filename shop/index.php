<?php
require __DIR__ . '/includes/init.php';
rl_event('BROWSE', ['page' => 'index']);
$products = sb_select('products', ['select' => 'id,name,description,base_price,stock,image_path', 'active' => 'eq.true', 'order' => 'id.asc']);
page_header('Cakes');
?>
<h1>Our cakes</h1>
<?php if (!$products): ?>
  <p class="muted">No cakes yet. (The admin adds products in the Admin area.)</p>
<?php endif; ?>
<div class="grid">
<?php foreach ($products as $p): ?>
  <div class="card">
    <a href="/product.php?id=<?= (int)$p['id'] ?>"><?= product_img_html($p) ?></a>
    <h3><a href="/product.php?id=<?= (int)$p['id'] ?>"><?= h($p['name']) ?></a></h3>
    <div class="price"><?= h(money($p['base_price'])) ?></div>
    <div class="muted"><?= (int)$p['stock'] > 0 ? (int)$p['stock'] . ' in stock' : 'Out of stock' ?></div>
    <p><a class="btn alt" href="/product.php?id=<?= (int)$p['id'] ?>">View</a></p>
  </div>
<?php endforeach; ?>
</div>
<?php page_footer();
