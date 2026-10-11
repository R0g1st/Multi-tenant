<?php
// Точка входа Adminer (замена index.php из образа adminer:4.8.1):
// подключает плагины из plugins-enabled и по умолчанию включает русский язык.
namespace docker {
	function adminer_object() {
		require_once('plugins/plugin.php');

		$plugins = [];
		foreach (glob('plugins-enabled/*.php') as $plugin) {
			$plugins[] = require($plugin);
		}

		return new \AdminerPlugin($plugins);
	}
}

namespace {
	if (basename($_SERVER['DOCUMENT_URI'] ?? $_SERVER['REQUEST_URI']) === 'adminer.css' && is_readable('adminer.css')) {
		header('Content-Type: text/css');
		readfile('adminer.css');
		exit;
	}

	// язык можно сменить внизу меню — выбор запомнится в cookie
	if (!isset($_COOKIE['adminer_lang'])) {
		$_COOKIE['adminer_lang'] = 'ru';
	}

	function adminer_object() {
		return \docker\adminer_object();
	}

	require('adminer.php');
}
