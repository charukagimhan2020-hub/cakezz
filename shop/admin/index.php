<?php
require dirname(__DIR__) . '/includes/init.php';
require dirname(__DIR__) . '/includes/admin_layout.php';
require_admin();
$on = rulelock_enabled(true);
page_header('Admin');
admin_nav();
?>
<h1>Admin</h1>
<div class="card">
  <h3>RuleLock AI is <?= $on ? 'ON' : 'OFF' ?></h3>
  <p class="muted"><?= $on
      ? 'Every checkout is reviewed by RuleLock.'
      : 'RuleLock is skipped. The shop trusts everything the browser sends (vulnerable on purpose).' ?></p>
  <form method="post" action="/admin/toggle.php">
    <?= csrf_field() ?>
    <input type="hidden" name="enable" value="<?= $on ? '0' : '1' ?>">
    <button class="btn" id="toggleBtn" data-turn-on="<?= $on ? '0' : '1' ?>"><?= $on ? 'Turn RuleLock AI OFF' : 'Turn RuleLock AI ON' ?></button>
  </form>
</div>
<script>
// window.open must run inside the click handler, otherwise the browser blocks the new tab.
document.getElementById('toggleBtn').addEventListener('click', function () {
  if (this.dataset.turnOn === '1') window.open('/monitor/', '_blank');
});
</script>
<?php page_footer();
