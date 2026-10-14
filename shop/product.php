<?php
require __DIR__ . '/includes/init.php';
$id = int_from($_GET['id'] ?? 0);
$rows = sb_select('products', ['select' => 'id,name,description,base_price,stock,image_path', 'id' => 'eq.' . $id, 'active' => 'eq.true', 'limit' => 1]);
if (!$rows) { http_response_code(404); page_header('Not found'); echo '<h1>Cake not found</h1><p><a href="/index.php">Back to the shop</a></p>'; page_footer(); exit; }
$p = $rows[0];
rl_event('BROWSE', ['page' => 'product', 'product_id' => $id]);
$u = current_user();
$stock = (int)$p['stock'];
page_header($p['name']);
?>
<div class="two">
  <div><?= product_img_html($p, 'pimg big') ?></div>
  <div>
    <h1><?= h($p['name']) ?></h1>
    <p><?= nl2br(h($p['description'])) ?></p>
    <p class="price" style="font-size:1.4rem"><?= h(money($p['base_price'])) ?></p>
    <p class="muted"><?= $stock > 0 ? $stock . ' in stock' : 'Out of stock' ?></p>
<?php if (!$u): ?>
    <p><a href="/login.php">Log in</a> or <a href="/signup.php">sign up</a> to buy.</p>
<?php elseif ($u['role'] === 'admin'): ?>
    <p class="muted">Admins cannot buy. Use a customer account.</p>
<?php else: ?>
    <form method="post" action="/cart.php">
      <?= csrf_field() ?>
      <input type="hidden" name="product_id" value="<?= (int)$p['id'] ?>">
      <label for="q">Quantity</label>
      <input class="qty" id="q" type="number" name="quantity" value="1" min="1">
      <p class="actions">
        <button class="btn" name="action" value="add" <?= $stock < 1 ? 'disabled' : '' ?>>Add to cart</button>
        <button class="btn alt" name="action" value="buy" <?= $stock < 1 ? 'disabled' : '' ?>>Buy now</button>
      </p>
    </form>
<?php endif; ?>
  </div>
</div>
<?php page_footer();
